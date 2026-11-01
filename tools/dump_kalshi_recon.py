"""Read-only Kalshi dump for cloud-agent reconcile.

Uses secrets/kalshi_private_key.pem + secrets/kalshi_key_id.txt (already the
kitchen layout). Writes JSON under the Drive stamp so Google Drive sync can
hand the pack to a Cloud Agent. Does not place, cancel, or sell.

    python -u tools/dump_kalshi_recon.py
    python -u tools/dump_kalshi_recon.py --days 3
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_private  # noqa: E402
from prediction_paths import DRIVE_STAMP, RAW_DIR, ensure_dirs  # noqa: E402

ET = ZoneInfo("America/New_York")
PACK_NAME = "kalshi_recon_dump"
SETTLEMENTS_PATH = "/trade-api/v2/portfolio/settlements"
POSITIONS_PATH = "/trade-api/v2/portfolio/positions"


def _now_et() -> datetime:
    return datetime.now(ET)


def _stamp() -> str:
    return _now_et().strftime("%Y%m%d_%H%M%S")


def _iso(dt: datetime) -> str:
    return dt.astimezone(ET).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, default=str) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def _get_json(path: str, query: dict | None = None, timeout: float = 45) -> dict:
    status, text = kalshi_private.signed_call("GET", path, query=query, timeout=timeout)
    try:
        body = json.loads(text) if text else {}
    except json.JSONDecodeError:
        body = {"_raw": text[:4000]}
    if not isinstance(body, dict):
        body = {"_value": body}
    return {"http_status": status, "ok": status == 200, "body": body, "pulled_at": _iso(_now_et())}


def pull_balance() -> dict:
    status, text = kalshi_private.balance()
    try:
        body = json.loads(text) if text else {}
    except json.JSONDecodeError:
        body = {"_raw": text[:4000]}
    cash = kalshi_private.parse_balance_usd(body)
    return {
        "http_status": status,
        "ok": status == 200 and cash is not None,
        "balance_usd": str(cash) if cash is not None else None,
        "body": body if isinstance(body, dict) else {"_value": body},
        "pulled_at": _iso(_now_et()),
        "note": "cash only; portfolio_value is open positions, not spendable",
    }


def pull_positions() -> dict:
    return _get_json(
        POSITIONS_PATH,
        query={"limit": "1000", "count_filter": "position"},
        timeout=45,
    )


def pull_fills(*, min_ts: int, limit: int = 200, max_pages: int = 40) -> dict:
    fills: list = []
    cursor = ""
    pages = 0
    last_status = 0
    errors: list[dict] = []
    while pages < max_pages:
        query: dict[str, str] = {
            "limit": str(limit),
            "min_ts": str(min_ts),
        }
        if cursor:
            query["cursor"] = cursor
        status, text = kalshi_private.get_fills(query, timeout=45)
        last_status = status
        pages += 1
        try:
            body = json.loads(text) if text else {}
        except json.JSONDecodeError:
            errors.append({"page": pages, "http_status": status, "raw": text[:1000]})
            break
        if status != 200 or not isinstance(body, dict):
            errors.append({"page": pages, "http_status": status, "body": body})
            break
        batch = body.get("fills") or []
        if isinstance(batch, list):
            fills.extend(item for item in batch if isinstance(item, dict))
        cursor = str(body.get("cursor") or "").strip()
        if not cursor or not batch:
            break
        time.sleep(0.15)
    return {
        "http_status": last_status,
        "ok": last_status == 200 and not errors,
        "min_ts": min_ts,
        "min_ts_et": _iso(datetime.fromtimestamp(min_ts, tz=timezone.utc)),
        "n": len(fills),
        "pages": pages,
        "fills": fills,
        "errors": errors,
        "pulled_at": _iso(_now_et()),
    }


def pull_settlements(*, min_ts: int, limit: int = 200, max_pages: int = 40) -> dict:
    rows: list = []
    cursor = ""
    pages = 0
    last_status = 0
    errors: list[dict] = []
    while pages < max_pages:
        query: dict[str, str] = {
            "limit": str(limit),
            "min_ts": str(min_ts),
        }
        if cursor:
            query["cursor"] = cursor
        status, text = kalshi_private.signed_call(
            "GET", SETTLEMENTS_PATH, query=query, timeout=45
        )
        last_status = status
        pages += 1
        try:
            body = json.loads(text) if text else {}
        except json.JSONDecodeError:
            errors.append({"page": pages, "http_status": status, "raw": text[:1000]})
            break
        if status != 200 or not isinstance(body, dict):
            errors.append({"page": pages, "http_status": status, "body": body})
            break
        batch = body.get("settlements") or []
        if isinstance(batch, list):
            rows.extend(item for item in batch if isinstance(item, dict))
        cursor = str(body.get("cursor") or "").strip()
        if not cursor or not batch:
            break
        time.sleep(0.15)
    return {
        "http_status": last_status,
        "ok": last_status == 200 and not errors,
        "min_ts": min_ts,
        "min_ts_et": _iso(datetime.fromtimestamp(min_ts, tz=timezone.utc)),
        "n": len(rows),
        "pages": pages,
        "settlements": rows,
        "errors": errors,
        "pulled_at": _iso(_now_et()),
        "endpoint": SETTLEMENTS_PATH,
    }


def build_pack(*, days: int) -> dict:
    import kalshi_same_direction as ksd

    now = _now_et()
    start = now - timedelta(days=days)
    min_ts = int(start.astimezone(timezone.utc).timestamp())
    balance = pull_balance()
    time.sleep(0.2)
    positions = pull_positions()
    time.sleep(0.2)
    fills = pull_fills(min_ts=min_ts)
    time.sleep(0.2)
    settlements = pull_settlements(min_ts=min_ts)
    sett_rows = list(settlements.get("settlements") or [])
    fill_rows = list(fills.get("fills") or [])
    stacks = ksd.find_same_direction_stacks(sett_rows + fill_rows)
    # Unique by event.
    seen = set()
    unique_stacks = []
    for row in stacks:
        key = row.get("event")
        if key in seen:
            continue
        seen.add(key)
        unique_stacks.append(row)
    venue_pnl = sum((ksd.settlement_pnl_usd(r) or __import__("decimal").Decimal("0")) for r in sett_rows)
    return {
        "pack": PACK_NAME,
        "written_at": _iso(now),
        "days": days,
        "window_start_et": _iso(start),
        "window_end_et": _iso(now),
        "secrets_used": {
            "key_id_path": _rel(kalshi_private.KEY_ID_PATH),
            "private_key_path": _rel(kalshi_private.KEY_PATH),
            "key_id_present": kalshi_private.KEY_ID_PATH.is_file(),
            "private_key_present": kalshi_private.KEY_PATH.is_file(),
        },
        "balance": balance,
        "positions": positions,
        "fills": fills,
        "settlements": settlements,
        "same_direction_stacks": unique_stacks,
        "venue_settlement_pnl_usd": ksd.money(venue_pnl),
        "ready_for_cloud_agent": True,
        "note": (
            "Read-only dump. No orders. Upload/sync the Drive folder, then tell the "
            "Cloud Agent the pack is ready. same_direction_stacks flags Yes-on-A + "
            "No-on-B complementary Kalshi markets (not a lock)."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump Kalshi balance/positions/fills for reconcile.")
    parser.add_argument("--days", type=int, default=3, help="Lookback window in days (default 3).")
    args = parser.parse_args()
    days = max(1, int(args.days))

    ensure_dirs()
    if not kalshi_private.KEY_PATH.is_file() or not kalshi_private.KEY_ID_PATH.is_file():
        print("MISSING secrets. Need both:")
        print(f"  {kalshi_private.KEY_PATH}")
        print(f"  {kalshi_private.KEY_ID_PATH}")
        print("Key id = UUID on the Kalshi API keys page (one line). PEM = private key download.")
        return 2

    print(f"pulling Kalshi recon dump days={days} ...", flush=True)
    pack = build_pack(days=days)
    stamp = _stamp()
    drive_dir = DRIVE_STAMP / PACK_NAME
    local_dir = RAW_DIR / PACK_NAME
    drive_dir.mkdir(parents=True, exist_ok=True)
    local_dir.mkdir(parents=True, exist_ok=True)

    stamped = f"{PACK_NAME}_{stamp}.json"
    latest = f"{PACK_NAME}_latest.json"
    ready = "READY.txt"

    paths = []
    for folder in (drive_dir, local_dir):
        paths.append(_write(folder / stamped, pack))
        paths.append(_write(folder / latest, pack))
        ready_path = folder / ready
        ready_path.write_text(
            "\n".join(
                [
                    f"written_at={pack['written_at']}",
                    f"days={days}",
                    f"balance_http={pack['balance'].get('http_status')}",
                    f"balance_usd={pack['balance'].get('balance_usd')}",
                    f"positions_http={pack['positions'].get('http_status')}",
                    f"positions_n={len(((pack['positions'].get('body') or {}).get('market_positions')) or [])}",
                    f"fills_http={pack['fills'].get('http_status')}",
                    f"fills_n={pack['fills'].get('n')}",
                    f"settlements_http={pack['settlements'].get('http_status')}",
                    f"settlements_n={pack['settlements'].get('n')}",
                    f"file={stamped}",
                    "Tell the Cloud Agent: Kalshi recon dump is ready in Drive.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        paths.append(ready_path)

    bal_ok = pack["balance"].get("ok")
    pos_ok = pack["positions"].get("ok")
    fills_ok = pack["fills"].get("ok")
    set_ok = pack["settlements"].get("ok")
    print(f"balance     http={pack['balance'].get('http_status')} cash={pack['balance'].get('balance_usd')}")
    print(f"positions   http={pack['positions'].get('http_status')}")
    print(f"fills       http={pack['fills'].get('http_status')} n={pack['fills'].get('n')}")
    print(f"settlements http={pack['settlements'].get('http_status')} n={pack['settlements'].get('n')}")
    print("wrote:")
    for path in paths:
        print(f"  {path}")
    print()
    print("Drive path (sync this):")
    print(f"  {drive_dir / latest}")
    print("When Google Drive finishes syncing, tell the agent the dump is ready.")

    if not (bal_ok and pos_ok and fills_ok):
        print("WARNING: one or more core pulls failed. Check HTTP codes above.", flush=True)
        return 1
    if not set_ok:
        print(
            "NOTE: settlements pull failed or empty; fills+balance+positions are still usable.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
