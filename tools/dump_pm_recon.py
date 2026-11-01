"""Read-only multi-venue prediction recon dump for Cloud Agent reconcile.

Pulls whatever secrets exist on this PC:
  - kalshi: balance / positions / fills / settlements (via dump_kalshi_recon)
  - polymarket: portfolio activities
  - gemini: balances + prediction order history
  - novig: balance + fills

Writes Drive + local JSON. Does not place, cancel, or sell.

    python -u tools/dump_pm_recon.py
    python -u tools/dump_pm_recon.py --days 3
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

from prediction_paths import DRIVE_STAMP, RAW_DIR, ensure_dirs  # noqa: E402
import dump_kalshi_recon as kalshi_dump  # noqa: E402

ET = ZoneInfo("America/New_York")
PACK_NAME = "pm_recon_dump"


def _now_et() -> datetime:
    return datetime.now(ET)


def _iso(dt: datetime) -> str:
    return dt.astimezone(ET).isoformat(timespec="seconds")


def _stamp() -> str:
    return _now_et().strftime("%Y%m%d_%H%M%S")


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def _json_body(status: int, text: str) -> dict:
    try:
        body = json.loads(text) if text else {}
    except json.JSONDecodeError:
        body = {"_raw": (text or "")[:4000]}
    if not isinstance(body, dict) and not isinstance(body, list):
        body = {"_value": body}
    return {
        "http_status": status,
        "ok": status == 200,
        "body": body,
        "pulled_at": _iso(_now_et()),
    }


def pull_polymarket(*, days: int) -> dict:
    try:
        import polymarket_us_live as poly
    except Exception as exc:
        return {"ok": False, "error": f"import {type(exc).__name__}: {exc}", "present": False}
    key_file = getattr(poly, "KEY_FILE", None)
    secret_file = getattr(poly, "SECRET_FILE", None)
    secrets_ok = bool(
        key_file
        and secret_file
        and Path(key_file).is_file()
        and Path(secret_file).is_file()
    )
    min_ts = int((_now_et() - timedelta(days=days)).astimezone(timezone.utc).timestamp())
    if not secrets_ok:
        return {
            "ok": False,
            "present": False,
            "error": "missing secrets/polymarket_api_key.txt or polymarket_api_secret.txt",
            "min_ts": min_ts,
        }
    try:
        status, text = poly.get_activities({"limit": "200"})
    except Exception as exc:
        return {
            "ok": False,
            "present": True,
            "error": f"{type(exc).__name__}: {exc}",
            "min_ts": min_ts,
        }
    out = _json_body(status, text)
    out["present"] = True
    out["min_ts"] = min_ts
    out["note"] = "Read-only activities. Positions/settlement may need a later pull."
    return out


def pull_gemini() -> dict:
    try:
        import gemini_private as gem
    except Exception as exc:
        return {"ok": False, "error": f"import {type(exc).__name__}: {exc}", "present": False}
    key_file = getattr(gem, "KEY_FILE", None)
    secret_file = getattr(gem, "SECRET_FILE", None)
    present = bool(
        key_file
        and secret_file
        and Path(key_file).is_file()
        and Path(secret_file).is_file()
    )
    if not present:
        return {
            "ok": False,
            "present": False,
            "error": "missing secrets/gemini_api_key.txt or gemini_api_secret.txt",
        }
    try:
        status, text = gem.get_order_history()
    except Exception as exc:
        return {"ok": False, "present": True, "error": f"{type(exc).__name__}: {exc}"}
    out = _json_body(status, text)
    out["present"] = True
    out["note"] = "Prediction order history. Balances are a separate signed call on trading PC."
    return out


def pull_novig() -> dict:
    try:
        import novig_live as novig
    except Exception as exc:
        return {"ok": False, "error": f"import {type(exc).__name__}: {exc}", "present": False}
    try:
        bal_status, bal = novig.balance_usd()
    except Exception as exc:
        bal_status, bal = 0, None
        bal_err = f"{type(exc).__name__}: {exc}"
    else:
        bal_err = None
    try:
        fill_status, fill_text = novig.list_fills({"limit": "200"})
    except Exception as exc:
        return {
            "ok": False,
            "present": True,
            "balance": {
                "http_status": bal_status,
                "balance_usd": str(bal) if bal is not None else None,
                "error": bal_err,
            },
            "error": f"fills {type(exc).__name__}: {exc}",
        }
    fills = _json_body(fill_status, fill_text)
    return {
        "ok": bool(fills.get("ok")) and bal is not None,
        "present": True,
        "balance": {
            "http_status": bal_status,
            "ok": bal is not None,
            "balance_usd": str(bal) if bal is not None else None,
            "error": bal_err,
            "pulled_at": _iso(_now_et()),
        },
        "fills": fills,
        "note": "Read-only balance + fills.",
    }


def build_pack(*, days: int) -> dict:
    now = _now_et()
    venues: dict[str, dict] = {}

    # Kalshi reuses the proven pack builder when secrets exist.
    try:
        import kalshi_private

        have = kalshi_private.KEY_PATH.is_file() and kalshi_private.KEY_ID_PATH.is_file()
    except Exception:
        have = False
    if have:
        print("pulling kalshi ...", flush=True)
        venues["kalshi"] = kalshi_dump.build_pack(days=days)
        time.sleep(0.2)
    else:
        venues["kalshi"] = {
            "ok": False,
            "present": False,
            "error": "missing secrets/kalshi_private_key.pem or kalshi_key_id.txt",
        }

    print("pulling polymarket ...", flush=True)
    venues["polymarket"] = pull_polymarket(days=days)
    time.sleep(0.2)
    print("pulling gemini ...", flush=True)
    venues["gemini"] = pull_gemini()
    time.sleep(0.2)
    print("pulling novig ...", flush=True)
    venues["novig"] = pull_novig()

    present = [name for name, block in venues.items() if block.get("present") or block.get("pack") == "kalshi_recon_dump"]
    # Kalshi pack uses pack name, mark present when built.
    if isinstance(venues.get("kalshi"), dict) and venues["kalshi"].get("pack") == "kalshi_recon_dump":
        venues["kalshi"]["present"] = True
        if "kalshi" not in present:
            present.append("kalshi")

    return {
        "pack": PACK_NAME,
        "written_at": _iso(now),
        "days": days,
        "window_start_et": _iso(now - timedelta(days=days)),
        "window_end_et": _iso(now),
        "venues": venues,
        "venues_present": present,
        "ready_for_cloud_agent": True,
        "note": (
            "Read-only multi-venue dump. Missing shops stay in the pack with present=false. "
            "Run run_pm_venue_kitchen_check.bat after Drive sync."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump all PM venues for reconcile.")
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args()
    days = max(1, int(args.days))
    ensure_dirs()

    pack = build_pack(days=days)
    stamp = _stamp()
    drive_dir = DRIVE_STAMP / PACK_NAME
    local_dir = RAW_DIR / PACK_NAME
    stamped = f"{PACK_NAME}_{stamp}.json"
    latest = f"{PACK_NAME}_latest.json"

    paths = []
    for folder in (drive_dir, local_dir):
        folder.mkdir(parents=True, exist_ok=True)
        paths.append(_write(folder / stamped, pack))
        paths.append(_write(folder / latest, pack))
        ready = folder / "READY.txt"
        ready.write_text(
            "\n".join(
                [
                    f"written_at={pack['written_at']}",
                    f"days={days}",
                    f"venues_present={','.join(pack.get('venues_present') or [])}",
                    f"file={stamped}",
                    "Tell the Cloud Agent: PM recon dump is ready in Drive.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        paths.append(ready)

    print(f"venues_present: {pack.get('venues_present')}")
    for name, block in (pack.get("venues") or {}).items():
        print(f"  {name}: present={block.get('present')} ok={block.get('ok')}")
    print("wrote:")
    for path in paths:
        print(f"  {path}")
    # Soft success if at least one venue present.
    if not pack.get("venues_present"):
        print("WARNING: no venue secrets/dumps available.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
