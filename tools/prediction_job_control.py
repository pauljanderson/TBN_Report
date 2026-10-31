"""Start, restart, or report the prediction-market supervisor and catalog scan.

Double-click the repo-root bats. This file does not place an order.
status/start/restart-lock leave leftover watch alone. systems --lock on turns
Lock gap (A) back on after a one-leg fill and clears raw/orders_stopped.json.
It does not stop Tennis crossover / C / D / E.
job_status.html is a kitchen scoreboard — do not emit What you asked /
In plain English (same as dashboard.html).
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from prediction_paths import (
    DRIVE_STAMP as STAMP,
    ONE_LEG_WATCH,
    ORDERS_STOP,
    PYCACHE_DIR,
    RAW_DIR as RAW,
    ROOT,
    ensure_dirs,
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)
import win_hidden  # noqa: E402
STATUS_PAGE = STAMP / "job_status.html"
SUPERVISOR_SCRIPT = ROOT / "tools" / "live_game_pollers.py"
SCAN_SCRIPT = STAMP / "overnight_scan.py"
STRATEGY_B_SCRIPT = ROOT / "tools" / "live_strategy_b.py"
SETTLE_RECONCILE_SCRIPT = ROOT / "tools" / "live_pm_settle_reconcile.py"
SUPERVISOR_LOG = RAW / "live_supervisor.log"
SCAN_LOG = RAW / "overnight_scan.log"
STRATEGY_B_LOG = RAW / "strategy_b.log"
POLLER_STATUS = RAW / "live_pollers_status.json"
STRATEGY_B_STATE = RAW / "strategy_b_watch.json"
ET = ZoneInfo("America/New_York")


def deadline_ok(*_args, **_kwargs) -> tuple[bool, str]:
    """No collection clock. Start/restart always allowed (except a second Strategy B)."""
    return True, (
        "The 8 AM collection deadline is gone. Paul's bats start/stop. "
        "Max open locks 3 / Strategy B matches 2 remain the cap."
    )


def _ps_rows() -> list[dict]:
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and ("
        "$_.CommandLine -like '*live_game_pollers.py*' -or "
        "$_.CommandLine -like '*overnight_scan.py*' -or "
        "$_.CommandLine -like '*live_strategy_b.py*' -or "
        "$_.CommandLine -like '*live_cfb_favorite.py*' -or "
        "$_.CommandLine -like '*live_spread_t0.py*' -or "
        "$_.CommandLine -like '*live_tennis_t0_dog.py*' -or "
        "$_.CommandLine -like '*live_tennis_t0_spread.py*' -or "
        "$_.CommandLine -like '*live_soccer_t0_total.py*' -or "
        "$_.CommandLine -like '*live_lock_sender.py*' -or "
        "$_.CommandLine -like '*live_pm_settle_reconcile.py*') } | "
        "ForEach-Object { "
        "'{0}|{1}|{2}|{3}' -f $_.ProcessId, $_.ParentProcessId, "
        "$_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss'), "
        "($_.CommandLine -replace '\\|','/') }"
    )
    try:
        out = win_hidden.check_output(
            win_hidden.powershell_argv(script),
            text=True,
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Could not list processes: {exc}")
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[0].strip())
            parent = int(parts[1].strip())
        except ValueError:
            continue
        rows.append(
            {
                "pid": pid,
                "parent": parent,
                "started": parts[2].strip(),
                "cmd": parts[3].strip(),
            }
        )
    return rows


def _poller_key_from_cmd(cmd: str) -> str:
    text = str(cmd or "")
    if "--poll-one" not in text:
        return ""
    return text.split("--poll-one", 1)[1].strip().split()[0]


def intended_live_pollers(path: Path | None = None) -> list[dict]:
    """Supervisor's last published live set. Missing file means unknown, not zero."""
    target = path or POLLER_STATUS
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    games = data.get("games") if isinstance(data, dict) else None
    if not isinstance(games, list):
        return []
    rows = []
    for item in games:
        if not isinstance(item, dict):
            continue
        pid = item.get("pid")
        try:
            pid_n = int(pid) if pid not in (None, "") else None
        except (TypeError, ValueError):
            pid_n = None
        rows.append(
            {
                "key": str(item.get("key") or ""),
                "pid": pid_n,
                "sport": str(item.get("sport") or ""),
                "game": str(item.get("game") or ""),
            }
        )
    return [row for row in rows if row["key"]]


def poller_pid_compare(intended: list[dict], children: list[dict], poll_all: list[dict] | None = None) -> list[dict]:
    by_intended = {row["key"]: row for row in intended if row.get("key")}
    by_actual: dict[str, dict] = {}
    extras = []
    merged = (poll_all or [None])[0] if poll_all else None
    if merged:
        merged_pid = merged.get("pid")
        rows = []
        for key, want in sorted(by_intended.items()):
            want_pid = want.get("pid")
            status = "match" if want_pid in (None, merged_pid) else "pid mismatch"
            rows.append(
                {
                    "key": key,
                    "sport": want.get("sport") or "",
                    "game": want.get("game") or "",
                    "intended_pid": want_pid or merged_pid,
                    "actual_pid": merged_pid,
                    "started": merged.get("started") or "",
                    "status": status,
                }
            )
        for row in children:
            rows.append(
                {
                    "key": _poller_key_from_cmd(row.get("cmd") or "") or "(leftover --poll-one)",
                    "sport": "",
                    "game": "",
                    "intended_pid": None,
                    "actual_pid": row.get("pid"),
                    "started": row.get("started") or "",
                    "status": "extra process",
                }
            )
        if not by_intended:
            rows.append(
                {
                    "key": "--poll-all",
                    "sport": "",
                    "game": "",
                    "intended_pid": merged_pid,
                    "actual_pid": merged_pid,
                    "started": merged.get("started") or "",
                    "status": "match",
                }
            )
        return rows
    for row in children:
        key = _poller_key_from_cmd(row.get("cmd") or "")
        if not key:
            extras.append(row)
            continue
        by_actual[key] = row
    rows = []
    for key in sorted(set(by_intended) | set(by_actual)):
        want = by_intended.get(key)
        got = by_actual.get(key)
        want_pid = want.get("pid") if want else None
        got_pid = got.get("pid") if got else None
        if want and got and want_pid == got_pid:
            status = "match"
        elif want and not got:
            status = "missing process"
        elif got and not want:
            status = "extra process"
        else:
            status = "pid mismatch"
        rows.append(
            {
                "key": key,
                "sport": (want or {}).get("sport") or "",
                "game": (want or {}).get("game") or "",
                "intended_pid": want_pid,
                "actual_pid": got_pid,
                "started": (got or {}).get("started") or "",
                "status": status,
            }
        )
    for row in extras:
        rows.append(
            {
                "key": "(no --poll-one key)",
                "sport": "",
                "game": "",
                "intended_pid": None,
                "actual_pid": row.get("pid"),
                "started": row.get("started") or "",
                "status": "extra process",
            }
        )
    return rows


def _count_processes(*names: str) -> dict[str, int]:
    counts = {name: 0 for name in names}
    if os.name != "nt" or not names:
        return counts
    listed = ",".join(f"'{name}'" for name in names)
    script = (
        f"$want = @({listed}); "
        "Get-Process -Name $want -ErrorAction SilentlyContinue | "
        "Group-Object Name | ForEach-Object { '{0}={1}' -f $_.Name, $_.Count }"
    )
    try:
        out = win_hidden.check_output(
            win_hidden.powershell_argv(script),
            text=True,
            errors="replace",
            timeout=8,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return counts
    for part in (out or "").splitlines():
        if "=" not in part:
            continue
        name, text = part.split("=", 1)
        try:
            counts[name.strip()] = int(text.strip() or 0)
        except ValueError:
            continue
    return counts


def classify(rows: list[dict]) -> dict:
    supervisor = []
    scan = []
    children = []
    poll_all = []
    lock_sender = []
    strategy_b = []
    cfb_favorite = []
    spread_t0 = []
    tennis_t0_dog = []
    tennis_t0_spread = []
    soccer_t0_total = []
    settle_reconcile = []
    for row in rows:
        cmd = row["cmd"].lower()
        if "python" not in cmd:
            continue
        if "get-ciminstance" in cmd or "prediction_job_control.py" in cmd:
            continue
        cmd = row["cmd"]
        if "live_strategy_b.py" in cmd:
            strategy_b.append(row)
        elif "live_cfb_favorite.py" in cmd:
            cfb_favorite.append(row)
        elif "live_spread_t0.py" in cmd:
            spread_t0.append(row)
        elif "live_tennis_t0_dog.py" in cmd:
            tennis_t0_dog.append(row)
        elif "live_tennis_t0_spread.py" in cmd:
            tennis_t0_spread.append(row)
        elif "live_soccer_t0_total.py" in cmd:
            soccer_t0_total.append(row)
        elif "live_pm_settle_reconcile.py" in cmd:
            settle_reconcile.append(row)
        elif "live_lock_sender.py" in cmd:
            lock_sender.append(row)
        elif "live_game_pollers.py" in cmd and "--poll-one" in cmd:
            children.append(row)
        elif "live_game_pollers.py" in cmd and "--poll-all" in cmd:
            poll_all.append(row)
        elif "live_game_pollers.py" in cmd and "--lock-send" in cmd:
            lock_sender.append(row)
        elif "live_game_pollers.py" in cmd:
            supervisor.append(row)
        elif "overnight_scan.py" in cmd and "prediction_market_arb_exhaustive_20261017" in cmd:
            scan.append(row)
    return {
        "supervisor": supervisor,
        "scan": scan,
        "children": children,
        "poll_all": poll_all,
        "lock_sender": lock_sender,
        "strategy_b": strategy_b,
        "cfb_favorite": cfb_favorite,
        "spread_t0": spread_t0,
        "tennis_t0_dog": tennis_t0_dog,
        "tennis_t0_spread": tennis_t0_spread,
        "soccer_t0_total": soccer_t0_total,
        "settle_reconcile": settle_reconcile,
    }


def _last_line(path: Path) -> str:
    if not path.exists():
        return "(log file not found)"
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 8192))
            blob = handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return f"(could not read log: {exc})"
    lines = [line.strip() for line in blob.splitlines() if line.strip()]
    return lines[-1] if lines else "(log is empty)"


def orders_latch() -> tuple[bool, str, str]:
    if not ORDERS_STOP.exists():
        return False, "not set", ""
    try:
        data = json.loads(ORDERS_STOP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True, "set (file present, unreadable)", ""
    reason = str(data.get("reason") or "").strip()
    when = str(data.get("timestamp") or "").strip()
    bits = ["set"]
    if reason:
        bits.append(reason)
    if when:
        bits.append(when)
    return True, " - ".join(bits), when


def _fmt_et(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith(" ET") and "T" not in text:
        return text
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if when.tzinfo is None:
        when = when.replace(tzinfo=ET)
    return when.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S ET")


def _et_date(value) -> str:
    text = _fmt_et(value)
    return text[:10] if len(text) >= 10 else ""


def _cash_text(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return str(value)
    return "$" + format(number.quantize(Decimal("0.01")), "f")


def _venue_label(venue: str) -> str:
    text = str(venue or "").strip()
    if not text:
        return ""
    known = {"kalshi": "Kalshi", "polymarket": "Polymarket", "gemini": "Gemini", "novig": "Novig"}
    return known.get(text.lower(), text)


def _player_name(raw: str) -> str:
    text = str(raw or "").strip()
    lower = text.lower()
    if lower.endswith(" wins"):
        text = text[:-5].strip()
    return text


def _same_game(left: str, right: str) -> bool:
    a = " ".join(str(left or "").lower().split())
    b = " ".join(str(right or "").lower().split())
    return bool(a and a == b)


def _bet_label(side: str, player: str) -> str:
    pay = str(side or "").strip().lower()
    who = _player_name(player)
    if pay in {"yes", "no"}:
        pay = pay.title()
    return " ".join(part for part in (pay, who) if part).strip()


def _load_watch(path: Path | None = None) -> dict:
    target = path or ONE_LEG_WATCH
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def leftover_watch_rows(watch: dict | None = None) -> list[dict]:
    """Unwrap {watches: [...]} so a wrapper without top-level game still has games."""
    data = watch if isinstance(watch, dict) else {}
    if not data:
        return []
    raw = data.get("watches")
    if isinstance(raw, list) and raw:
        rows = [item for item in raw if isinstance(item, dict)]
        if rows:
            return rows
    return [data]


def _send_line_text() -> str:
    try:
        import live_lock_orders

        return live_lock_orders.send_line()
    except Exception:
        return "NET_MAX"


def _lock_open_text() -> str:
    try:
        import live_lock_orders

        return str(len(live_lock_orders.open_lock_keys()))
    except Exception:
        return "—"


def last_skip_text(path: Path | None = None) -> str:
    """Last send-gate / flatten skip from lock_last_skip.json. Empty file is none."""
    target = path or (RAW / "lock_last_skip.json")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return "none"
    if not isinstance(data, dict):
        return "none"
    reason = str(data.get("reason") or "").strip() or "skip"
    try:
        import live_lock_orders

        reason = live_lock_orders.rewrite_send_line_copy(reason)
    except Exception:
        pass
    game = str(data.get("game") or "").strip()
    when = _fmt_et(data.get("at") or "")
    bits = [reason]
    if game:
        bits.append(game)
    if when:
        bits.append(when)
    return " — ".join(bits)


def leftover_watch_text(watch: dict | None = None) -> str:
    data = watch if isinstance(watch, dict) else _load_watch()
    if not data:
        return "no file"
    rows = leftover_watch_rows(data)
    if not rows:
        return "no file"
    parts = []
    for row in rows:
        game = str(row.get("game") or "").strip() or "unknown game"
        if row.get("stopped"):
            when = _fmt_et(row.get("stopped_at") or "")
            reason = str(row.get("stop_reason") or "").strip()
            bits = ["stopped", game]
            if when:
                bits.append(when)
            if reason:
                bits.append(reason)
            parts.append(" — ".join(bits))
            continue
        started = _fmt_et(row.get("started_at") or row.get("last_tick_at") or "")
        bits = ["watching", game]
        if started:
            bits.append("since " + started)
        parts.append(" — ".join(bits))
    return " | ".join(parts)


def _leg_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("venue") or "").strip().lower(),
        str(row.get("instrument") or "").strip().lower(),
        str(row.get("side") or "").strip().lower(),
    )


def _leg_from_watch(watch: dict) -> dict | None:
    venue = str(watch.get("filled_venue") or "").strip()
    if not venue:
        return None
    side = str(watch.get("filled_side") or "").strip().lower()
    player = _player_name(str(watch.get("claim_side") or ""))
    return {
        "sport": str(watch.get("sport") or "").strip(),
        "game": str(watch.get("game") or "").strip(),
        "bet": _bet_label(side, player),
        "side": side,
        "player": player,
        "venue": venue,
        "instrument": str(watch.get("filled_instrument") or "").strip(),
        "fill": _cash_text(watch.get("fill_px")),
        "time_et": _fmt_et(watch.get("started_at") or watch.get("last_tick_at") or ""),
        "why": "One leg filled and the other missed, so Lock gap (A) is off. B–E stay on.",
        "source": "watch",
    }


def _fill_cash(sent: dict | None, fill: dict | None, events: list[dict], venue: str, instrument: str) -> str:
    import order_ledger

    cash = ""
    avg = ""
    if fill:
        cash = str(fill.get("cash") or "").strip()
        avg = str(fill.get("avg") or "").strip()
    if cash:
        return _cash_text(cash)
    matched = next(
        (
            item
            for item in events
            if item.get("event") in {"filled", "one_leg"}
            and str(item.get("venue") or "") == venue
            and str(item.get("instrument") or "") == instrument
            and item.get("price") not in (None, "")
        ),
        None,
    )
    raw = avg or (str(matched.get("price")) if matched else "")
    if not raw and sent and sent.get("limit_price"):
        raw = str(sent.get("limit_price"))
    if not raw:
        return ""
    number = order_ledger._dec(raw)
    side = str((sent or {}).get("side") or "").lower()
    if number is not None and venue == "kalshi" and side == "no":
        return _cash_text(Decimal("1") - number)
    return _cash_text(raw)


def _ledger_leftover_legs() -> list[dict]:
    """One-leg fills from orders.jsonl + order_io.jsonl.

    A Kalshi HTTP 201 with fill_count >= 1 counts even when the orders.jsonl
    send row stayed pending after a ledger write error.
    """
    import order_ledger

    claims = order_ledger._load_jsonl(order_ledger.ORDERS)
    io_rows = order_ledger._io_status()
    io_list = [row for row in order_ledger._load_jsonl(order_ledger.ORDER_IO) if str(row.get("kind") or "") == "order"]
    found: list[dict] = []
    for context, events in order_ledger._attempts(claims):
        sends = [item for item in events if item.get("event") == "sent"]
        if not sends:
            continue
        terminal = next(
            (item for item in reversed(events) if item.get("event") in {"one_leg", "both_unfilled"}),
            None,
        )
        filled_keys = {
            (str(item.get("venue") or ""), str(item.get("instrument") or ""))
            for item in events
            if item.get("event") == "filled"
        }
        used_io: set[str] = set()
        send_fills = [
            order_ledger._io_fill_for_sent(item, context, io_rows, io_list, used_io) for item in sends
        ]
        for item, fill in zip(sends, send_fills):
            if fill and fill.get("filled"):
                filled_keys.add((str(item.get("venue") or ""), str(item.get("instrument") or "")))
        if terminal and terminal.get("event") == "one_leg":
            filled_keys.add((str(terminal.get("venue") or ""), str(terminal.get("instrument") or "")))
        if len(filled_keys) != 1:
            continue
        venue, instrument = next(iter(filled_keys))
        sent = next(
            (
                item
                for item in sends
                if str(item.get("venue") or "") == venue and str(item.get("instrument") or "") == instrument
            ),
            None,
        )
        fill = None
        if sent is not None:
            fill = send_fills[sends.index(sent)]
        side = str((sent or {}).get("side") or "").lower()
        if fill and fill.get("side"):
            side = str(fill.get("side") or side).lower()
        if terminal and terminal.get("event") == "one_leg" and not side:
            side = str(terminal.get("side") or "").lower()
        player = _player_name(str(context.get("side") or ""))
        sport = str(context.get("sport") or "").strip()
        if not sport:
            sport = str(context.get("bet_key") or "").split("\t", 1)[0].strip()
        when = ""
        if sent:
            when = str(sent.get("sent_at") or "")
        if not when:
            when = str(context.get("compared_at") or "")
        found.append(
            {
                "sport": sport,
                "game": str(context.get("game") or "").strip(),
                "bet": _bet_label(side, player),
                "side": side,
                "player": player,
                "venue": venue,
                "instrument": instrument,
                "fill": _fill_cash(sent, fill, events, venue, instrument),
                "time_et": _fmt_et(when),
                "why": "One leg filled and the other missed, so Lock gap (A) is off. B–E stay on.",
                "source": "ledger",
            }
        )
    return found


def leftover_filled_legs(
    latch_on: bool,
    latch_when: str = "",
    *,
    watch: dict | None = None,
) -> list[dict]:
    """Filled leftover legs while Lock gap (A) is off after a one-leg fill.

    Source of truth is orders.jsonl + order_io.jsonl + one_leg_watch.json,
    not only the latch reason string. Lists each one-leg fill (Wawrinka
    case: Kalshi No Landaluce and Polymarket Yes Wawrinka). B–E stay on.
    """
    if not latch_on:
        return []
    watch_row = watch if isinstance(watch, dict) else _load_watch()
    try:
        legs = _ledger_leftover_legs()
    except Exception:
        legs = []
    watch_rows = leftover_watch_rows(watch_row) if watch_row else []
    keys = {_leg_key(row) for row in legs}
    for item in watch_rows:
        watch_leg = _leg_from_watch(item)
        if watch_leg and _leg_key(watch_leg) not in keys:
            legs.append(watch_leg)
            keys.add(_leg_key(watch_leg))
    watch_games = [
        str(item.get("game") or "").strip()
        for item in watch_rows
        if str(item.get("game") or "").strip()
    ]
    latch_day = _et_date(latch_when)
    kept: list[dict] = []
    if watch_games:
        kept = [
            row
            for row in legs
            if any(_same_game(row.get("game") or "", game) for game in watch_games)
        ]
    if not kept and latch_day:
        kept = [row for row in legs if _et_date(row.get("time_et") or "") == latch_day]
    if not kept:
        kept = list(legs)
    unique: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for row in kept:
        key = _leg_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    unique.sort(key=lambda row: (row.get("time_et") or "", row.get("venue") or ""))
    return unique


def _load_strategy_b(path: Path | None = None) -> dict:
    target = path or STRATEGY_B_STATE
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _open_now_cell(value) -> str:
    """Systems table Open now is a count. Cap stays in Max."""
    try:
        import prediction_systems

        return prediction_systems.open_now_display(value)
    except Exception:
        text = "" if value is None else str(value).strip()
        if "/" in text:
            left = text.split("/", 1)[0].strip()
            if left.lstrip("-").isdigit():
                return left
        return text or ""


def _systems_snapshot(jobs: dict | None = None, snapshot=None, positions=None) -> list[dict]:
    try:
        import prediction_systems

        return prediction_systems.status_rows(jobs, snapshot=snapshot, positions=positions)
    except Exception:
        return []


def _systems_html(snap: dict) -> str:
    line = str(snap.get("send_line") or _send_line_text())
    rows = snap.get("systems") or []
    if not rows:
        try:
            import prediction_systems

            rows = prediction_systems.status_rows()
        except Exception:
            rows = []
    headers = [
        ("Sys", "text"),
        ("Name", "text"),
        ("On/off", "text"),
        ("Stake $", "num"),
        ("Size", "num"),
        ("Max open", "num"),
        ("Open now", "num"),
        ("PID", "num"),
        ("Last action", "text"),
    ]
    head = "".join(_sortable_th(label, kind) for label, kind in headers)
    body = []
    for item in rows:
        extra = item.get("extra_pids") or ""
        pid = str(item.get("pid") or "—")
        if extra:
            pid = f"{pid} extra {extra}"
        cells = [
            item.get("letter") or "",
            item.get("name") or "",
            item.get("on") or "",
            item.get("stake") or "",
            item.get("size") or "",
            item.get("max_open") or "",
            _open_now_cell(item.get("open")),
            pid,
            item.get("last") or "—",
        ]
        tds = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells)
        body.append(f"<tr>{tds}</tr>")
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        "<h2>Systems</h2>"
        '<p class="note">A Lock gap, B Tennis crossover, C CFB favorite, D T0 spreads, E Tennis T0 dog, F Tennis spread. '
        "<strong>D on except NFL</strong> — live D skips pro football / NFL "
        "(<code>d_skip_nfl_gathering</code>) until we have enough T0 spread data. "
        "College football and other sports stay on if D is on. systems.json D stays on. "
        "On/off, stake, and max open are <code>python tools/prediction_job_control.py systems</code> "
        "or double-click <code>run_prediction_systems.bat</code>. "
        f"A send cap is <strong>{html.escape(line)}</strong> "
        "(systems.json lock.net_max, else code default 0.984). "
        f"Set with <code>python tools/prediction_job_control.py systems --lock-net-max {html.escape(line)}</code> "
        "(alias <code>--lock-gap</code>). "
        "<code>--lock on --lock-max 3 --lock-stake 1</code> does not change the send cap. "
        "Lock pollers reread systems.json each tick (like D max); no restart. "
        "A one-leg lock fill turns <strong>A off only</strong> "
        "(<code>lock.on=false</code>); B–E stay on. "
        "Turn A back with <code>python tools/prediction_job_control.py systems --lock on</code>. "
        "Open now is the count of Positions rows by system. "
        "Max is the cap (Lock gap 3, others default 2). "
        "$1 ≈ 1 contract at these prices. Click column headers to sort. "
        '<a href="systems_abcd_cli_20261024.html">systems_abcd_cli_20261024.html</a> · '
        '<a href="system_e_t0_dog_20261025.html">system_e_t0_dog_20261025.html</a> · '
        '<a href="lock_net_max_099_20261025.html">lock_net_max_099_20261025.html</a>.</p>'
        f"{SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _positions_html(snap: dict) -> str:
    try:
        import job_status_positions

        bundle = snap.get("positions")
        if not isinstance(bundle, dict):
            bundle = job_status_positions.empty_bundle()
        return job_status_positions.render_table(bundle)
    except Exception:
        return ""


def _http_budget_snapshot() -> dict:
    """Kalshi/Gemini/Poly/Novig lock wait, skipped ticks, in-flight vs cap."""
    try:
        import venue_pace

        snap = venue_pace.health_snapshot()
        return snap if isinstance(snap, dict) else {"venues": {}, "updated": None}
    except Exception:
        return {"venues": {}, "updated": None}


def _http_budget_html(snap: dict) -> str:
    """Kitchen scoreboard HTTP budget. No What you asked block."""
    budget = snap.get("http_budget")
    if not isinstance(budget, dict):
        budget = _http_budget_snapshot()
    venues = budget.get("venues") if isinstance(budget.get("venues"), dict) else {}
    headers = [
        ("Platform", "text"),
        ("Interval s", "num"),
        ("In-flight / cap", "text"),
        ("Background cap", "num"),
        ("Send reserved", "num"),
        ("Lock wait ms (last)", "num"),
        ("Lock wait ms (ewma)", "num"),
        ("Lock wait ms (max)", "num"),
        ("Skipped ticks", "num"),
        ("Granted", "num"),
        ("Send granted", "num"),
        ("Health updated", "date"),
    ]
    head = "".join(_sortable_th(label, kind) for label, kind in headers)
    body = []
    order = ("kalshi", "gemini", "polymarket", "novig")
    for venue in order:
        row = venues.get(venue) if isinstance(venues.get(venue), dict) else {}
        inflight = int(row.get("in_flight") or row.get("inflight_count") or 0)
        cap = int(row.get("cap") or row.get("inflight_cap") or 0)
        cells = [
            str(row.get("label") or venue),
            f"{float(row.get('interval_s') or 0):.2f}",
            f"{inflight} / {cap}",
            str(int(row.get("background_limit") or 0)),
            str(int(row.get("reserved") or 0)),
            f"{float(row.get('lock_wait_ms') or row.get('lock_wait_ms_last') or 0):.1f}",
            f"{float(row.get('lock_wait_ms_ewma') or 0):.1f}",
            f"{float(row.get('lock_wait_ms_max') or 0):.1f}",
            str(int(row.get("skipped_ticks") or 0)),
            str(int(row.get("granted") or 0)),
            str(int(row.get("send_granted") or 0)),
            str(row.get("updated") or "—"),
        ]
        tds = "".join(f"<td>{html.escape(cell)}</td>" for cell in cells)
        body.append(f"<tr>{tds}</tr>")
    stamp = str(budget.get("updated") or "")
    stamp_note = f" Health file {html.escape(stamp)}." if stamp else ""
    return (
        "<h2>HTTP budget</h2>"
        '<p class="note">Shared per-platform HTTP queue. Background catalog / leftover / '
        "C-D-E slate walks skip when in-flight is at the background cap so 80 helpers "
        "do not convoy on the Kalshi file lock. Send-path REST confirm (B 50-cross, "
        "T0 send, lock send, dip GTC) uses the reserved seat and never skips. "
        "Click column headers to sort."
        f"{stamp_note}</p>"
        f"{SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _http_budget_line(snap: dict) -> str:
    budget = snap.get("http_budget") if isinstance(snap.get("http_budget"), dict) else {}
    venues = budget.get("venues") if isinstance(budget.get("venues"), dict) else {}
    bits = []
    for venue in ("kalshi", "gemini", "polymarket", "novig"):
        row = venues.get(venue) if isinstance(venues.get(venue), dict) else {}
        label = row.get("label") or venue
        inflight = int(row.get("in_flight") or row.get("inflight_count") or 0)
        cap = int(row.get("cap") or row.get("inflight_cap") or 0)
        skipped = int(row.get("skipped_ticks") or 0)
        wait_ms = float(row.get("lock_wait_ms") or row.get("lock_wait_ms_last") or 0)
        bits.append(f"{label} wait {wait_ms:.0f}ms skip {skipped} inflight {inflight}/{cap}")
    return "; ".join(bits) if bits else "—"


def _strategy_b_open(data: dict) -> list[dict]:
    open_stages = {
        "waiting_t0",
        "t0_filled_waiting_50_cross",
        "waiting_cross",
        "waiting_fav_dip",
        "fav_gtc_resting",
        "one_leg_miss",
    }
    rows = []
    for item in data.get("matches") or []:
        if isinstance(item, dict) and str(item.get("stage") or "") in open_stages:
            rows.append(item)
    return rows


def _reload_status_helpers() -> None:
    """Supervisor reloads this module each minute; helpers must reload too."""
    import importlib
    import sys

    for name in (
        "kalshi_ticker_decode",
        "open_count_sync",
        "job_status_positions",
        "prediction_systems",
        "orders_performance_refresh",
        "write_orders_performance",
        "write_dashboard",
        "order_ledger",
        "venue_pace",
    ):
        mod = sys.modules.get(name)
        if mod is not None:
            try:
                importlib.reload(mod)
            except Exception:
                pass


def snapshot() -> dict:
    _reload_status_helpers()
    jobs = classify(_ps_rows())
    sup = jobs["supervisor"][:1]
    scan = jobs["scan"][:1]
    b_jobs = jobs.get("strategy_b") or []
    latch_on, latch_text, latch_when = orders_latch()
    watch = _load_watch()
    try:
        filled_legs = leftover_filled_legs(latch_on, latch_when, watch=watch)
    except Exception:
        filled_legs = []
    intended = intended_live_pollers()
    children = jobs["children"]
    compare = poller_pid_compare(intended, children, jobs.get("poll_all"))
    consoles = _count_processes("OpenConsole", "conhost", "python")
    b_state = _load_strategy_b()
    venue = None
    try:
        import open_count_sync

        venue = open_count_sync.venue_snapshot()
        b_state = open_count_sync.overlay_currently_open(b_state, "tennis_crossover", venue)
        try:
            import orders_performance_refresh

            orders_performance_refresh.note_snapshot_closes(venue)
        except Exception:
            pass
    except Exception:
        venue = None
    positions = None
    try:
        import job_status_positions

        positions = job_status_positions.bundle_from_snapshot(venue, fetch_quotes=True)
    except Exception:
        positions = None
    return {
        "supervisor": sup[0] if sup else None,
        "supervisor_extra": jobs["supervisor"][1:],
        "scan": scan[0] if scan else None,
        "scan_extra": jobs["scan"][1:],
        "strategy_b": b_jobs[0] if b_jobs else None,
        "strategy_b_extra": b_jobs[1:],
        "cfb_favorite": (jobs.get("cfb_favorite") or [None])[0] if jobs.get("cfb_favorite") else None,
        "cfb_favorite_extra": (jobs.get("cfb_favorite") or [])[1:],
        "spread_t0": (jobs.get("spread_t0") or [None])[0] if jobs.get("spread_t0") else None,
        "spread_t0_extra": (jobs.get("spread_t0") or [])[1:],
        "tennis_t0_dog": (jobs.get("tennis_t0_dog") or [None])[0] if jobs.get("tennis_t0_dog") else None,
        "tennis_t0_dog_extra": (jobs.get("tennis_t0_dog") or [])[1:],
        "tennis_t0_spread": (jobs.get("tennis_t0_spread") or [None])[0] if jobs.get("tennis_t0_spread") else None,
        "tennis_t0_spread_extra": (jobs.get("tennis_t0_spread") or [])[1:],
        "soccer_t0_total": (jobs.get("soccer_t0_total") or [None])[0] if jobs.get("soccer_t0_total") else None,
        "soccer_t0_total_extra": (jobs.get("soccer_t0_total") or [])[1:],
        "settle_reconcile": (jobs.get("settle_reconcile") or [None])[0] if jobs.get("settle_reconcile") else None,
        "settle_reconcile_extra": (jobs.get("settle_reconcile") or [])[1:],
        "systems": _systems_snapshot(jobs, snapshot=venue, positions=positions),
        "positions": positions,
        "children": children,
        "poll_all": (jobs.get("poll_all") or [None])[0] if jobs.get("poll_all") else None,
        "poll_all_extra": (jobs.get("poll_all") or [])[1:],
        "lock_sender": (jobs.get("lock_sender") or [None])[0] if jobs.get("lock_sender") else None,
        "lock_sender_extra": (jobs.get("lock_sender") or [])[1:],
        "intended": intended,
        "poller_compare": compare,
        "consoles": consoles,
        "latch_on": latch_on,
        "latch_text": latch_text,
        "watch_text": leftover_watch_text(watch),
        "send_line": _send_line_text(),
        "lock_open": _lock_open_text(),
        "last_skip_text": last_skip_text(),
        "filled_legs": filled_legs,
        "supervisor_log": _last_line(SUPERVISOR_LOG),
        "scan_log": _last_line(SCAN_LOG),
        "strategy_b_log": _last_line(STRATEGY_B_LOG),
        "strategy_b_state": b_state,
        "deadline": None,
        "deadline_text": deadline_ok()[1],
        "checked": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET"),
        "http_budget": _http_budget_snapshot(),
    }


def _job_bits(row: dict | None, extra: list[dict]) -> str:
    if row is None:
        return "DOWN"
    text = f"UP  pid {row['pid']}  started {row['started']}"
    if extra:
        more = ", ".join(str(item["pid"]) for item in extra)
        text += f"  (extra pids {more})"
    return text


def print_status(snap: dict) -> None:
    print(f"Checked {snap['checked']}")
    print(f"Supervisor: {_job_bits(snap['supervisor'], snap['supervisor_extra'])}")
    print(f"Catalog scan: {_job_bits(snap['scan'], snap['scan_extra'])}")
    actual_n = len(snap["children"])
    intended_n = len(snap.get("intended") or [])
    poll_all = snap.get("poll_all")
    lock_sender = snap.get("lock_sender")
    print(f"Merged poller (--poll-all): {_job_bits(poll_all, snap.get('poll_all_extra') or [])}")
    print(f"Lock sender (A): {_job_bits(lock_sender, snap.get('lock_sender_extra') or [])}")
    print(f"Leftover --poll-one helpers: {actual_n}")
    print(f"Intended live set (supervisor status file): {intended_n}")
    compare = snap.get("poller_compare") or []
    mismatch = [row for row in compare if row.get("status") != "match"]
    print(f"Poller PID mismatches (missing/extra/pid differs): {len(mismatch)}")
    actual_pids = [str(row["pid"]) for row in snap["children"]]
    intended_pids = [str(row.get("pid") or "—") for row in (snap.get("intended") or [])]
    print(f"Actual python --poll-one PIDs: {', '.join(actual_pids) if actual_pids else '(none)'}")
    print(f"Intended PIDs: {', '.join(intended_pids) if intended_pids else '(none)'}")
    consoles = snap.get("consoles") or {}
    if consoles:
        print(
            "Consoles: "
            f"OpenConsole {consoles.get('OpenConsole', 0)}, "
            f"conhost {consoles.get('conhost', 0)}, "
            f"python {consoles.get('python', 0)}"
        )
    print(f"Deadline: {snap.get('deadline_text') or deadline_ok()[1]}")
    print(f"Tennis crossover (B): {_job_bits(snap.get('strategy_b'), snap.get('strategy_b_extra') or [])}")
    print(f"Settle reconcile: {_job_bits(snap.get('settle_reconcile'), snap.get('settle_reconcile_extra') or [])}")
    b_state = snap.get("strategy_b_state") or {}
    print(
        "Tennis crossover: "
        f"on={b_state.get('enabled', False)}  max_open={b_state.get('max_open_b_matches', 1)}  "
        f"open={b_state.get('currently_open', 0)}  "
        f"cadence={b_state.get('watch_cadence') or 'continuous / tick'}  "
        f"tennis starts 15m={b_state.get('cluster_15m', '—')} 60m={b_state.get('cluster_60m', '—')}"
    )
    try:
        import prediction_systems

        print(prediction_systems.format_status_table(snap.get("systems") or prediction_systems.status_rows()))
    except Exception as exc:
        print(f"Systems table: {type(exc).__name__}")
    pos = snap.get("positions") or {}
    footer = pos.get("footer") or {}
    print(
        "Positions: "
        f"{footer.get('count_text') or '0 rows'}  "
        f"open P&L {footer.get('pnl_text') or '—'}"
    )
    print(f"orders_stopped.json: {snap['latch_text']}")
    print(f"Leftover watch: {snap.get('watch_text') or 'no file'}")
    print(f"Send line (NET_MAX): {snap.get('send_line') or _send_line_text()}")
    print(f"Open lock pairs (max_open_locks): {snap.get('lock_open') or _lock_open_text()}")
    print(f"Last skip reason: {snap.get('last_skip_text') or 'none'}")
    print(f"HTTP budget: {_http_budget_line(snap)}")
    legs = snap.get("filled_legs") or []
    if snap.get("latch_on"):
        print("Lock gap (A) is off because one leg filled and the other missed. B–E stay on.")
        if not legs:
            print("Filled leftover legs: none found in orders.jsonl / order_io.jsonl / one_leg_watch.json")
        else:
            print(f"Filled leftover legs ({len(legs)}):")
            for row in legs:
                print(
                    f"  {row.get('sport') or ''} / {row.get('game') or ''} / "
                    f"{row.get('bet') or ''} / {_venue_label(str(row.get('venue') or ''))} / "
                    f"{row.get('fill') or ''} / {row.get('time_et') or ''}"
                )
    print(f"Supervisor log: {snap['supervisor_log']}")
    print(f"Scan log: {snap['scan_log']}")
    print(f"Status page: {STATUS_PAGE}")
    print("Check only: run_prediction_status.bat")
    print("Start a missing job: run_prediction_start.bat")
    print("Stop and start one of each: run_prediction_restart.bat")


def _sortable_th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _filled_legs_html(snap: dict) -> str:
    if not snap.get("latch_on"):
        return ""
    legs = snap.get("filled_legs") or []
    if not legs:
        return (
            '<div class="stop">'
            "<h2>Lock gap (A) is off</h2>"
            "<p>"
            + html.escape(str(snap.get("latch_text") or "orders_stopped.json is set"))
            + ". One leg filled and the other missed, so Lock gap (A) is off. "
            "Tennis crossover B, CFB favorite C, T0 spreads D, and tennis T0 dog E stay on. "
            "Turn A back with <code>python tools/prediction_job_control.py systems --lock on</code>. "
            "No filled leftover leg was found in "
            "orders.jsonl, order_io.jsonl, or one_leg_watch.json.</p>"
            "</div>"
        )
    headers = [
        ("Sport", "text"),
        ("Game", "text"),
        ("Bet", "text"),
        ("Venue", "text"),
        ("Fill cash/price", "num"),
        ("Time ET", "date"),
        ("Why Lock gap (A) is off", "text"),
    ]
    head = "".join(_sortable_th(label, kind) for label, kind in headers)
    rows = []
    for item in legs:
        cells = [
            item.get("sport") or "",
            item.get("game") or "",
            item.get("bet") or "",
            _venue_label(str(item.get("venue") or "")),
            item.get("fill") or "",
            item.get("time_et") or "",
            item.get("why") or "One leg filled and the other missed, so Lock gap (A) is off. B–E stay on.",
        ]
        tds = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells)
        rows.append(f"<tr>{tds}</tr>")
    return (
        '<div class="stop">'
        "<h2>Lock gap (A) is off</h2>"
        "<p>"
        + html.escape(str(snap.get("latch_text") or "orders_stopped.json is set"))
        + ". One leg filled and the other missed, so Lock gap (A) is off. "
        "Tennis crossover B, CFB favorite C, T0 spreads D, and tennis T0 dog E stay on. "
        "Turn A back with <code>python tools/prediction_job_control.py systems --lock on</code>, "
        "or wait until leftover is fully hedged/flattened. "
        "Leftover watch is continuous / tick (sleep at most 1s). Flatten-first leftover stays. "
        "Each filled leftover is listed below "
        "(from orders.jsonl, order_io.jsonl, and one_leg_watch.json — not only the latch reason).</p>"
        "</div>"
        "<h2>Filled leftover legs</h2>"
        '<p class="note">Click column headers to sort. These are the filled legs sitting unmatched. '
        "A Kalshi HTTP 201 with fill_count of 1 counts even if an orders.jsonl send row stayed pending.</p>"
        f"{SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


def _b_stage_label(stage: str, match: dict | None = None) -> str:
    match = match or {}
    names = {
        "waiting_t0": "waiting T0",
        "t0_filled_waiting_50_cross": "T0 filled waiting 50-cross",
        "waiting_cross": "waiting 50-cross (extras)",
        "waiting_fav_dip": "waiting fav dip at target " + str(match.get("fav_target") or "X"),
        "fav_gtc_resting": "fav GTC resting at " + str(match.get("fav_target") or "X"),
        "done": "done",
        "one_leg_miss": "one-leg miss",
        "absorbed": "absorbed",
        "abandoned": "abandoned",
        "postponed": "postponed",
        "queued": "queued",
    }
    return names.get(str(stage or ""), str(stage or ""))


def _strategy_b_html(snap: dict) -> str:
    proc = snap.get("strategy_b")
    extra = snap.get("strategy_b_extra") or []
    state = snap.get("strategy_b_state") or {}
    on = bool(state.get("enabled")) if state else False
    proc_state = "UP" if proc else "DOWN"
    max_open = state.get("max_open_b_matches", 1)
    currently = state.get("currently_open", len(_strategy_b_open(state)))
    cluster_15 = state.get("cluster_15m", "—")
    cluster_60 = state.get("cluster_60m", "—")
    note = str(state.get("cluster_note") or "")
    last = str(state.get("updated_at") or "")
    log_line = str(snap.get("strategy_b_log") or "")
    meta = (
        "<h2>Tennis crossover (Strategy B, research live)</h2>"
        '<p class="note">On/off, max_open, and currently open come from '
        "<code>strategy_b_watch.json</code> overlaid with venue positions "
        "(Poly qty &gt; 0 including partials, Kalshi qty ≥ 1, unique games, cache ≤ 60s). "
        "This is not the Yes+No lock bot and does not use orders_stopped.json. "
        "Click column headers to sort.</p>"
        f"{SWIPE_NOTE_HTML}"
        '<table class="status">'
        f"<tr><th>Strategy B process</th><td>{html.escape(proc_state)}"
        + (f" pid {html.escape(str(proc['pid']))}" if proc else "")
        + (f" extra pids {html.escape(', '.join(str(x['pid']) for x in extra))}" if extra else "")
        + "</td></tr>"
        f"<tr><th>On / off</th><td>{'on' if on else 'off'}</td></tr>"
        f"<tr><th>max_open_b_matches</th><td>{html.escape(str(max_open))}</td></tr>"
        f"<tr><th>Watch cadence</th><td>{html.escape(str(state.get('watch_cadence') or 'continuous / tick'))}</td></tr>"
        f"<tr><th>Currently open</th><td>{html.escape(str(currently))}</td></tr>"
        f"<tr><th>Tennis starts next 15 minutes</th><td>{html.escape(str(cluster_15))}</td></tr>"
        f"<tr><th>Tennis starts next 60 minutes</th><td>{html.escape(str(cluster_60))}</td></tr>"
        f"<tr><th>Cluster note</th><td>{html.escape(note or '—')}</td></tr>"
        f"<tr><th>State updated</th><td>{html.escape(last or '—')}</td></tr>"
        f"<tr><th>Last skip_reason</th><td>{html.escape(str(state.get('last_skip_reason') or state.get('late_t0_skip_reason') or '—'))}</td></tr>"
        f"<tr><th>Late-T0 skip_reason</th><td>{html.escape(str(state.get('late_t0_skip_reason') or '—'))}</td></tr>"
        f"<tr><th>T0 C / stack</th><td>{html.escape(str(state.get('t0_c_rule') or 'Send if both Yes in (0.10, 0.90) and all-in C (asks + documented taker fees) ≤ 1.05. All-in C>1.05 skip t0_allin_c_over_105. Do not gate on wire C_HI=1.01. Stack another 1-contract T0 pair while all-in with fees < $1, cap 10 pairs/match. Match slots are not extra contracts.'))}</td></tr>"
        f"<tr><th>50-cross</th><td>{html.escape(str(state.get('cross_rule') or 'REST both Yes asks. Send T0-dog extra only if favorite Yes is strictly below dog Yes AND all-in C (asks + documented taker fees) ≤ 1.05. Else skip cross_fav_not_below_dog or cross_allin_c_over_105; no extra, no dip from that illegal cross.'))}</td></tr>"
        f"<tr><th>Last Strategy B log line</th><td>{html.escape(log_line or '—')}</td></tr>"
        "</table>"
    )
    matches = [item for item in (state.get("matches") or []) if isinstance(item, dict)]
    open_rows = _strategy_b_open(state)
    show = open_rows or matches[-8:]
    headers = [
        ("Game", "text"),
        ("Venue", "text"),
        ("Stage", "text"),
        ("T0 Yes prices + fills", "text"),
        ("Last order id", "text"),
        ("Last order time", "date"),
        ("HTTP", "num"),
        ("Fill qty", "num"),
        ("Last quotes", "text"),
    ]
    head = "".join(_sortable_th(label, kind) for label, kind in headers)
    body = []
    for item in show:
        t0 = item.get("t0_yes") if isinstance(item.get("t0_yes"), dict) else {}
        bits = []
        for key in ("a", "b"):
            row = t0.get(key) if isinstance(t0.get(key), dict) else {}
            player = str(row.get("player") or key)
            price = str(row.get("fill_px") or row.get("price") or "")
            filled = "filled" if row.get("filled") else "open"
            bits.append(f"{player} {price} ({filled})")
        last_order = item.get("last_order") if isinstance(item.get("last_order"), dict) else {}
        quotes = item.get("last_quotes") if isinstance(item.get("last_quotes"), dict) else {}
        quote_bits = []
        for name, q in quotes.items():
            if isinstance(q, dict):
                quote_bits.append(f"{name} {q.get('ask') or ''}")
            else:
                quote_bits.append(f"{name} {q}")
        cells = [
            item.get("game") or "",
            item.get("venue") or "",
            _b_stage_label(str(item.get("stage") or ""), item),
            "; ".join(bits) or "—",
            last_order.get("id") or "",
            last_order.get("time") or "",
            "" if last_order.get("http") in (None, "") else str(last_order.get("http")),
            last_order.get("fill_qty") or "",
            "; ".join(quote_bits) or "—",
        ]
        tds = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells)
        body.append(f"<tr>{tds}</tr>")
    empty = "<tr><td colspan='9'>No open Strategy B match.</td></tr>"
    table = (
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body) if body else empty}</tbody>"
        "</table></div>"
    )
    queued = [item for item in (state.get("queued") or []) if isinstance(item, dict)]
    q_note = ""
    if queued:
        q_note = (
            '<p class="note">Queued because max_open_b_matches=1: '
            + html.escape("; ".join(str(item.get("game") or "") for item in queued[-8:]))
            + "</p>"
        )
    return meta + table + q_note


def _poller_compare_html(snap: dict) -> str:
    rows = snap.get("poller_compare") or []
    headers = [
        ("Key", "text"),
        ("Sport", "text"),
        ("Game", "text"),
        ("Intended PID", "num"),
        ("Actual python PID", "num"),
        ("Started", "date"),
        ("Status", "text"),
    ]
    head = "".join(_sortable_th(label, kind) for label, kind in headers)
    body = []
    for item in rows:
        cells = [
            item.get("key") or "",
            item.get("sport") or "",
            item.get("game") or "",
            "" if item.get("intended_pid") is None else str(item.get("intended_pid")),
            "" if item.get("actual_pid") is None else str(item.get("actual_pid")),
            item.get("started") or "",
            item.get("status") or "",
        ]
        tds = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells)
        body.append(f"<tr>{tds}</tr>")
    mismatch = sum(1 for item in rows if item.get("status") != "match")
    note = (
        f"{len(rows)} game key(s). {mismatch} mismatch(es) "
        "(missing process, extra process, or intended PID differs from the live python PID)."
    )
    return (
        "<h2>Intended vs actual python poller PIDs</h2>"
        f'<p class="note">{html.escape(note)} Click column headers to sort. '
        "Intended is the supervisor live set in live_pollers_status.json. "
        "Actual is a live <code>python -u ... --poll-one</code> process.</p>"
        f"{SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _nfl_catalog_html(snap: dict | None = None) -> str:
    """Today's pro football rows in sports_queue.json plus NFL poller count."""
    path = RAW / "sports_queue.json"
    fetched = "missing"
    games = []
    try:
        blob = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        fetched = str(blob.get("fetched_at") or "unknown")
        for sport in blob.get("sports") or []:
            if str(sport.get("sport") or "").lower() != "pro football":
                continue
            games = [g for g in (sport.get("matched") or []) if isinstance(g, dict)]
            break
    except (OSError, json.JSONDecodeError):
        games = []
    today = datetime.now(ET).date().isoformat()
    today_games = [g for g in games if str(g.get("date") or "") >= today]
    spread_n = 0
    for game in today_games:
        kalshi = game.get("kalshi") if isinstance(game.get("kalshi"), dict) else {}
        gem = game.get("gemini") if isinstance(game.get("gemini"), dict) else {}
        if kalshi.get("spread") or gem.get("spread") or game.get("kalshi_spread_ticker") or game.get("gemini_spread_ticker"):
            spread_n += 1
    children = (snap or {}).get("children") or []
    nfl_pollers = [
        row for row in children
        if "pro_football" in str(row.get("cmd") or row.get("key") or "").lower()
        or "nfl" in str(row.get("cmd") or "").lower()
    ]
    samples = []
    for game in today_games[:8]:
        title = game.get("title_kalshi") or game.get("title_gemini") or " ".join(str(c) for c in (game.get("codes") or []))
        kalshi = game.get("kalshi") if isinstance(game.get("kalshi"), dict) else {}
        gem = game.get("gemini") if isinstance(game.get("gemini"), dict) else {}
        samples.append(
            f"{game.get('date') or ''} {title} "
            f"K {kalshi.get('spread') or '—'} / G {gem.get('spread') or '—'}"
        )
    sample_html = "<br>".join(html.escape(s) for s in samples) or "None"
    return (
        '<div class="callout">'
        "<h2>NFL in D queue</h2>"
        f"<p>sports_queue.json fetched_at {html.escape(fetched)}. "
        f"Pro football matched {len(games)}. Today-or-later {len(today_games)} games, "
        f"{spread_n} with a spread sibling. NFL pollers now {len(nfl_pollers)} "
        f"(all python --poll-one {len(children)}).</p>"
        f"<p class='note'>Sample:<br>{sample_html}</p>"
        "<p class='note'><strong>D on except NFL.</strong> Live D skips pro football / NFL "
        "(<code>d_skip_nfl_gathering</code>) while gathering T0 spread prices. "
        "CFB and other sports stay on. D still rereads this file each tick. "
        "Trusted T0 is kickoff. Did not start a second live_strategy_b.py. Did not sell.</p>"
        "</div>"
    )


def write_page(snap: dict) -> None:
    """Kitchen scoreboard. Do not emit What you asked / In plain English."""
    def row(label: str, value: str) -> str:
        return (
            "<tr><th>"
            + html.escape(label)
            + "</th><td>"
            + html.escape(value)
            + "</td></tr>"
        )

    sup = snap["supervisor"]
    scan = snap["scan"]
    sup_state = "UP" if sup else "DOWN"
    scan_state = "UP" if scan else "DOWN"
    deadline_text = str(snap.get("deadline_text") or deadline_ok()[1])
    body = "\n".join(
        [
            row("Supervisor", sup_state),
            row("Supervisor pid", str(sup["pid"]) if sup else "—"),
            row("Supervisor started", sup["started"] if sup else "—"),
            row("Catalog scan", scan_state),
            row("Catalog scan pid", str(scan["pid"]) if scan else "—"),
            row("Catalog scan started", scan["started"] if scan else "—"),
            row("Merged poller (--poll-all)", _job_bits(snap.get("poll_all"), snap.get("poll_all_extra") or [])),
            row("Lock sender (A)", _job_bits(snap.get("lock_sender"), snap.get("lock_sender_extra") or [])),
            row("Leftover --poll-one helpers", str(len(snap["children"]))),
            row("Intended live set (supervisor status file)", str(len(snap.get("intended") or []))),
            row(
                "Poller PID mismatches",
                str(sum(1 for item in (snap.get("poller_compare") or []) if item.get("status") != "match")),
            ),
            row(
                "Console processes",
                "OpenConsole {oc} (Windows Terminal tabs), conhost {ch}, python {py}".format(
                    oc=(snap.get("consoles") or {}).get("OpenConsole", "—"),
                    ch=(snap.get("consoles") or {}).get("conhost", "—"),
                    py=(snap.get("consoles") or {}).get("python", "—"),
                ),
            ),
            row("In-match ticks", "All live sports we already poll (tennis, NFL, college football, and other catalog sports) on Kalshi, Gemini, Polymarket US, and Novig. Change-ticks only. Lookback tape, not more orders. See inmatch_tick_collection_20261021.html."),
            row(
                "Deadline",
                deadline_text,
            ),
            row(
                "Tennis crossover (B)",
                "{state}  on={on}  max_open={max_open}  currently open {n}".format(
                    state="UP" if snap.get("strategy_b") else "DOWN",
                    on="yes" if (snap.get("strategy_b_state") or {}).get("enabled") else "no",
                    max_open=(snap.get("strategy_b_state") or {}).get("max_open_b_matches", 1),
                    n=(snap.get("strategy_b_state") or {}).get("currently_open", 0),
                ),
            ),
            row(
                "Settle reconcile",
                _job_bits(snap.get("settle_reconcile"), snap.get("settle_reconcile_extra") or []),
            ),
            row(
                "Tennis starts next 15m / 60m",
                "{a} / {b}".format(
                    a=(snap.get("strategy_b_state") or {}).get("cluster_15m", "—"),
                    b=(snap.get("strategy_b_state") or {}).get("cluster_60m", "—"),
                ),
            ),
            row("orders_stopped.json", snap["latch_text"]),
            row("Leftover watch (continuous / tick)", str(snap.get("watch_text") or "no file")),
            row("Send line (NET_MAX)", str(snap.get("send_line") or _send_line_text())),
            row("Open lock pairs (max_open_locks)", str(snap.get("lock_open") or _lock_open_text())),
            row("Last skip reason", str(snap.get("last_skip_text") or "none")),
            row("HTTP budget", _http_budget_line(snap)),
            row("Filled leftover legs", str(len(snap.get("filled_legs") or [])) if snap.get("latch_on") else "—"),
            row("Raw data (this PC only)", str(RAW)),
            row("HTML reports (Drive)", str(STAMP)),
            row("Last supervisor log line", snap["supervisor_log"]),
            row("Last catalog scan log line", snap["scan_log"]),
            row("Checked", snap["checked"]),
        ]
    )
    stop_block = _filled_legs_html(snap)
    systems_block = _systems_html(snap)
    nfl_block = _nfl_catalog_html(snap)
    positions_block = _positions_html(snap)
    http_budget_block = _http_budget_html(snap)
    strategy_b_block = _strategy_b_html(snap)
    poller_block = _poller_compare_html(snap)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prediction job status</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.stop {{ background: #fef2f2; border: 1px solid #fecaca; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.stop h2 {{ margin: 0 0 0.4rem; color: #991b1b; }}
.note {{ color: #475569; font-size: 0.95rem; }}
table.status {{ border-collapse: collapse; width: 100%; margin: 0 0 1rem; }}
table.status th, table.status td {{ border: 1px solid #d8dee9; padding: 0.45rem 0.6rem; vertical-align: top; text-align: left; }}
table.status th {{ width: 16rem; background: #f8fafc; }}
.up {{ color: #166534; font-weight: 600; }}
.down {{ color: #991b1b; font-weight: 600; }}
.updated {{ font-size: 1.1rem; margin: 0.25rem 0 1rem; }}
__SORTABLE_TH_CSS__
</style>
</head>
<body>
<h1>Prediction job status</h1>
<p class="updated"><strong>Updated {html.escape(snap["checked"])}</strong> (Eastern Time)</p>
<p>Supervisor is <span class="{('up' if sup else 'down')}">{sup_state}</span>.
Catalog scan is <span class="{('up' if scan else 'down')}">{scan_state}</span>.
Tennis crossover is <span class="{('up' if snap.get('strategy_b') else 'down')}">{('UP' if snap.get('strategy_b') else 'DOWN')}</span>.</p>
<p class="note">{html.escape(deadline_text)}</p>
{systems_block}
{nfl_block}
{positions_block}
{http_budget_block}
{stop_block}
{strategy_b_block}
<table class="status">
{body}
</table>
{poller_block}
<h2>What to double-click</h2>
<ul>
<li><code>run_prediction_status.bat</code> refreshes this page and prints up or down. It does not start or stop anything.</li>
<li><code>run_prediction_start.bat</code> starts a supervisor, catalog scan, or Strategy B only when that one is missing. It never refuses because a clock passed. If a job is already running, it leaves it.</li>
<li><code>run_prediction_restart.bat</code> stops the current supervisor, its live-game helpers, the catalog scan, and Strategy B, then starts one of each so they load the current code. No 8 AM clock and no +12h bump. Use <code>python tools/prediction_job_control.py reload-lock</code> to reload only the lock supervisor and leave B/C/D/E.</li>
<li><code>run_prediction_orders_on.bat</code> turns Lock gap (A) back on (<code>systems --lock on</code>) after a one-leg fill. It does not stop Tennis crossover / C / D / E and does not start a second B.</li>
<li><code>run_prediction_systems.bat</code> prints the Systems table (on/off, stake, max, pid). Pass flags to turn a system on or off without starting a second Tennis crossover.</li>
</ul>
__SORTABLE_TABLE_SCRIPT__
</body>
</html>
"""
    page = page.replace("__SORTABLE_TH_CSS__", SORTABLE_TH_CSS).replace(
        "__SORTABLE_TABLE_SCRIPT__", SORTABLE_TABLE_SCRIPT
    )
    page = inject_report_page_extras(page)
    STATUS_PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(STATUS_PAGE)
    try:
        import t0_all_games_stats

        t0_all_games_stats.maybe_rebuild()
    except Exception:
        pass
    try:
        import write_dashboard

        write_dashboard.refresh_from_job_status(snap)
    except Exception:
        pass


def _stop_pids(pids: list[int]) -> None:
    if not pids:
        return
    id_list = ",".join(str(pid) for pid in pids)
    script = (
        f"@({id_list}) | ForEach-Object {{ "
        "Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
    )
    win_hidden.run(
        win_hidden.powershell_argv(script),
        check=False,
    )


def _wait_until_clear(timeout: float = 20.0, *, include_strategy_b: bool = True, include_cd: bool = True) -> dict:
    deadline = time.time() + timeout
    jobs = classify(_ps_rows())
    while time.time() < deadline:
        left = jobs["supervisor"] + jobs["scan"] + jobs["children"] + (jobs.get("poll_all") or []) + (jobs.get("lock_sender") or [])
        if include_strategy_b:
            left += jobs.get("strategy_b") or []
        if include_cd:
            left += jobs.get("cfb_favorite") or []
            left += jobs.get("spread_t0") or []
            left += jobs.get("tennis_t0_dog") or []
            left += jobs.get("tennis_t0_spread") or []
            left += jobs.get("soccer_t0_total") or []
        if not left:
            return jobs
        time.sleep(0.5)
        jobs = classify(_ps_rows())
    return jobs


def start_missing(jobs: dict | None = None) -> int:
    _, note = deadline_ok()
    print(note)
    if jobs is None:
        jobs = classify(_ps_rows())
    if len(jobs["supervisor"]) > 1 or len(jobs["scan"]) > 1:
        print("More than one supervisor or catalog scan is already running. Not starting another.")
        return 1
    started = []
    if not jobs["supervisor"]:
        _spawn(SUPERVISOR_SCRIPT, RAW / "live_supervisor.console.log")
        started.append("supervisor")
    else:
        print(f"Supervisor already running pid {jobs['supervisor'][0]['pid']}. Left it.")
    if not jobs["scan"]:
        _spawn(SCAN_SCRIPT, RAW / "overnight_scan.console.log")
        started.append("catalog scan")
    else:
        print(f"Catalog scan already running pid {jobs['scan'][0]['pid']}. Left it.")
    if ensure_strategy_b(jobs):
        started.append("tennis crossover")
    else:
        b_row = (jobs.get("strategy_b") or [{}])[0]
        if b_row.get("pid"):
            print(f"Tennis crossover already running pid {b_row.get('pid')}. Left it.")
    try:
        import prediction_systems

        for sid, label in (
            ("cfb_favorite", "CFB favorite"),
            ("spread_t0", "T0 spreads"),
            ("tennis_t0_dog", "Tennis T0 dog"),
            ("tennis_t0_spread", "F Tennis spread"),
            ("soccer_t0_total", "G Soccer total"),
        ):
            if prediction_systems.ensure_system(sid, jobs):
                started.append(label)
            else:
                pids = prediction_systems.pids_for(sid, jobs)
                if pids:
                    print(f"{label} already running pid {pids[0]}. Left it.")
    except Exception as exc:
        print(f"C/D spawn skipped: {type(exc).__name__}")
    if ensure_settle_reconcile(jobs):
        started.append("settle reconcile")
    else:
        rec_row = (jobs.get("settle_reconcile") or [{}])[0]
        if rec_row.get("pid"):
            print(f"Settle reconcile already running pid {rec_row.get('pid')}. Left it.")
    if started:
        time.sleep(2)
        print("Started: " + ", ".join(started))
    else:
        print("Started: nothing")
    return 0


def _spawn(script: Path, console_log: Path, *, hidden: bool = True) -> None:
    """Start a job with no visible console. hidden=True is the only path; the flag stays for callers."""
    ensure_dirs()
    handle = console_log.open("a", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(PYCACHE_DIR)
    win_hidden.popen(
        [sys.executable, "-u", str(script)],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
        close_fds=True,
        env=env,
        new_group=True,
    )


def ensure_settle_reconcile(jobs: dict | None = None) -> bool:
    """Start the venue-true settle reconciler if missing. Never a second copy."""
    jobs = jobs or classify(_ps_rows())
    if jobs.get("settle_reconcile"):
        return False
    _spawn(SETTLE_RECONCILE_SCRIPT, RAW / "pm_settle_reconcile.console.log", hidden=True)
    return True


def ensure_strategy_b(jobs: dict | None = None) -> bool:
    """Start Tennis crossover if it is on and missing. Never a second copy."""
    try:
        import prediction_systems

        if not prediction_systems.is_on("tennis_crossover"):
            return False
    except Exception:
        pass
    jobs = jobs or classify(_ps_rows())
    if jobs.get("strategy_b"):
        return False
    _spawn(STRATEGY_B_SCRIPT, RAW / "strategy_b.console.log", hidden=True)
    return True


def reload_catalog_scan() -> dict:
    """Stop catalog scan process(es), start exactly one. Leave supervisor, pollers, B/C/D/E."""
    jobs = classify(_ps_rows())
    before = [row.get("pid") for row in (jobs.get("scan") or [])]
    b_before = [row.get("pid") for row in (jobs.get("strategy_b") or [])]
    if before:
        print("Stopping catalog scan pid(s) " + ", ".join(str(pid) for pid in before) + ".")
        _stop_pids(before)
        deadline = time.time() + 20.0
        while time.time() < deadline:
            left = classify(_ps_rows()).get("scan") or []
            if not left:
                break
            time.sleep(0.5)
        still = classify(_ps_rows()).get("scan") or []
        if still:
            print("Catalog scan still listed after stop: " + ", ".join(str(row["pid"]) for row in still))
            return {
                "ok": False,
                "before": before,
                "after": [row.get("pid") for row in still],
                "strategy_b_before": b_before,
                "strategy_b_after": b_before,
            }
    _spawn(SCAN_SCRIPT, RAW / "overnight_scan.console.log")
    time.sleep(1.2)
    after = classify(_ps_rows())
    scan = [row.get("pid") for row in (after.get("scan") or [])]
    b_after = [row.get("pid") for row in (after.get("strategy_b") or [])]
    print("Started catalog scan pid(s) " + ", ".join(str(pid) for pid in scan) + ".")
    return {
        "ok": len(scan) == 1,
        "before": before,
        "after": scan,
        "strategy_b_before": b_before,
        "strategy_b_after": b_after,
    }


def reload_strategy_b() -> int:
    """Stop only live_strategy_b.py and start one new copy. Pollers, latch, and lock leftover stay."""
    jobs = classify(_ps_rows())
    pids = [row["pid"] for row in (jobs.get("strategy_b") or [])]
    if pids:
        print("Stopping Strategy B pid(s) " + ", ".join(str(pid) for pid in pids) + ".")
        _stop_pids(pids)
        deadline = time.time() + 20.0
        while time.time() < deadline:
            left = classify(_ps_rows()).get("strategy_b") or []
            if not left:
                break
            time.sleep(0.5)
        still = classify(_ps_rows()).get("strategy_b") or []
        if still:
            print("Strategy B still listed after stop: " + ", ".join(str(row["pid"]) for row in still))
            return 1
    _spawn(STRATEGY_B_SCRIPT, RAW / "strategy_b.console.log", hidden=True)
    print("Started Strategy B.")
    return 0


def restart() -> int:
    jobs = classify(_ps_rows())
    pids = [
        row["pid"]
        for row in jobs["supervisor"]
        + jobs["children"]
        + (jobs.get("poll_all") or [])
        + (jobs.get("lock_sender") or [])
        + jobs["scan"]
        + (jobs.get("strategy_b") or [])
        + (jobs.get("cfb_favorite") or [])
        + (jobs.get("spread_t0") or [])
        + (jobs.get("tennis_t0_dog") or [])
        + (jobs.get("tennis_t0_spread") or [])
        + (jobs.get("soccer_t0_total") or [])
        + (jobs.get("settle_reconcile") or [])
    ]
    print(f"Stopping {len(pids)} process(es).")
    _stop_pids(pids)
    left = _wait_until_clear()
    still = (
        left["supervisor"]
        + left["children"]
        + (left.get("poll_all") or [])
        + (left.get("lock_sender") or [])
        + left["scan"]
        + (left.get("strategy_b") or [])
        + (left.get("cfb_favorite") or [])
        + (left.get("spread_t0") or [])
        + (left.get("tennis_t0_dog") or [])
        + (left.get("tennis_t0_spread") or [])
        + (left.get("soccer_t0_total") or [])
        + (left.get("settle_reconcile") or [])
    )
    if still:
        print("Some processes were still listed after the stop: " + ", ".join(str(row["pid"]) for row in still))
        return 1
    return start_missing({"supervisor": [], "scan": [], "children": []})


def reload_one_lock_supervisor() -> dict:
    """Stop lock supervisor(s) and pollers (open-set lives in their RAM), start one supervisor.

    Leaves catalog scan, Tennis crossover, C, D, and E. Never a second
    live_strategy_b.py. Does not sell. Does not touch NET_MAX.
    """
    jobs = classify(_ps_rows())
    before = {
        "supervisor": [row.get("pid") for row in (jobs.get("supervisor") or [])],
        "poller_n": len(jobs.get("children") or []),
        "poll_all": [row.get("pid") for row in (jobs.get("poll_all") or [])],
        "lock_sender": [row.get("pid") for row in (jobs.get("lock_sender") or [])],
        "scan": [row.get("pid") for row in (jobs.get("scan") or [])],
        "strategy_b": [row.get("pid") for row in (jobs.get("strategy_b") or [])],
        "cfb_favorite": [row.get("pid") for row in (jobs.get("cfb_favorite") or [])],
        "spread_t0": [row.get("pid") for row in (jobs.get("spread_t0") or [])],
        "tennis_t0_dog": [row.get("pid") for row in (jobs.get("tennis_t0_dog") or [])],
        "tennis_t0_spread": [row.get("pid") for row in (jobs.get("tennis_t0_spread") or [])],
        "soccer_t0_total": [row.get("pid") for row in (jobs.get("soccer_t0_total") or [])],
    }
    pids = [
        row["pid"]
        for row in (jobs.get("supervisor") or [])
        + (jobs.get("children") or [])
        + (jobs.get("poll_all") or [])
        + (jobs.get("lock_sender") or [])
    ]
    if pids:
        _stop_pids(pids)
        deadline = time.time() + 20.0
        while time.time() < deadline:
            left = classify(_ps_rows())
            if (
                not left.get("supervisor")
                and not left.get("children")
                and not left.get("poll_all")
                and not left.get("lock_sender")
            ):
                break
            time.sleep(0.4)
    left = classify(_ps_rows())
    start_missing(left)
    time.sleep(1.5)
    after = classify(_ps_rows())
    return {
        "before": before,
        "supervisor": [row.get("pid") for row in (after.get("supervisor") or [])],
        "poller_n": len(after.get("children") or []),
        "poll_all": [row.get("pid") for row in (after.get("poll_all") or [])],
        "lock_sender": [row.get("pid") for row in (after.get("lock_sender") or [])],
        "scan": [row.get("pid") for row in (after.get("scan") or [])],
        "strategy_b": [row.get("pid") for row in (after.get("strategy_b") or [])],
        "cfb_favorite": [row.get("pid") for row in (after.get("cfb_favorite") or [])],
        "spread_t0": [row.get("pid") for row in (after.get("spread_t0") or [])],
        "tennis_t0_dog": [row.get("pid") for row in (after.get("tennis_t0_dog") or [])],
        "tennis_t0_spread": [row.get("pid") for row in (after.get("tennis_t0_spread") or [])],
        "soccer_t0_total": [row.get("pid") for row in (after.get("soccer_t0_total") or [])],
        "notes": "one lock supervisor reloaded; pollers respawned under it; B/C/D/E/F/G/scan left",
    }


def restart_lock() -> int:
    """Stop supervisor, live pollers, and catalog scan. Leave Tennis crossover / C / D running."""
    jobs = classify(_ps_rows())
    pids = [
        row["pid"]
        for row in jobs["supervisor"]
        + jobs["children"]
        + (jobs.get("poll_all") or [])
        + (jobs.get("lock_sender") or [])
        + jobs["scan"]
    ]
    print(f"Stopping {len(pids)} lock/scan process(es). Tennis crossover / C / D / E left running.")
    _stop_pids(pids)
    left = _wait_until_clear(include_strategy_b=False, include_cd=False)
    still = left["supervisor"] + left["children"] + (left.get("poll_all") or []) + (left.get("lock_sender") or []) + left["scan"]
    if still:
        print("Some processes were still listed after the stop: " + ", ".join(str(row["pid"]) for row in still))
        return 1
    return start_missing(left)


def main(argv: list[str]) -> int:
    action = (argv[1] if len(argv) > 1 else "status").strip().lower()
    if action == "systems":
        import prediction_systems

        code = prediction_systems.systems_cli(argv[2:])
        snap = snapshot()
        write_page(snap)
        return code
    if action == "status":
        snap = snapshot()
        write_page(snap)
        print_status(snap)
        return 0
    if action == "start":
        code = start_missing()
        snap = snapshot()
        write_page(snap)
        print_status(snap)
        return code
    if action == "restart":
        code = restart()
        snap = snapshot()
        write_page(snap)
        print_status(snap)
        return code
    if action in ("restart-lock", "restart_lock"):
        code = restart_lock()
        snap = snapshot()
        write_page(snap)
        print_status(snap)
        return code
    if action in ("reload-lock", "reload_lock"):
        info = reload_one_lock_supervisor()
        snap = snapshot()
        write_page(snap)
        print_status(snap)
        print(
            "reload-lock: supervisor {before} -> {after}; B {b}; C {c}; D {d}; E {e}; F {f}; G {g}; scan {scan}".format(
                before=info.get("before", {}).get("supervisor") or [],
                after=info.get("supervisor") or [],
                b=info.get("strategy_b") or [],
                c=info.get("cfb_favorite") or [],
                d=info.get("spread_t0") or [],
                e=info.get("tennis_t0_dog") or [],
                f=info.get("tennis_t0_spread") or [],
                g=info.get("soccer_t0_total") or [],
                scan=info.get("scan") or [],
            )
        )
        return 0
    print("Use status, start, restart, restart-lock, reload-lock, or systems.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
