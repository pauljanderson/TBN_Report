"""Read-only dump: Aboian vs Hardt kitchen tape vs Kalshi/Poly. No orders. No secrets."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_private  # noqa: E402
import live_pm_settle_reconcile as rec  # noqa: E402
import polymarket_us_live  # noqa: E402
from prediction_paths import RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = RAW / "aboian_hardt_dump_20261030.json"
TICKERS = (
    "KXATPCHALLENGERMATCH-26OCT30ABOHAR-ABO",
    "KXATPCHALLENGERMATCH-26OCT30ABOHAR-HAR",
)
SLUG = "aec-atp-valabo-nichar-2026-10-30"
NEEDLES = ("aboian", "hardt", "abohar", "valabo", "nichar")
KEEP_EVENTS = {
    "sent",
    "filled",
    "flatten",
    "one_leg",
    "confirm",
    "venue_confirm",
    "result",
    "skip",
    "claim",
}


def hit(obj) -> bool:
    return any(n in json.dumps(obj, default=str).lower() for n in NEEDLES)


def slim(row: dict) -> dict:
    drop = {
        "api_key",
        "secret",
        "signature",
        "passphrase",
        "private_key",
        "authorization",
        "token",
        "note",
    }
    out = {}
    for key, value in row.items():
        if str(key).lower() in drop:
            if key == "note":
                text = str(value or "")
                if "insufficient" in text.lower() or "error" in text.lower() or "fill" in text.lower():
                    out[key] = text[:400]
            continue
        if isinstance(value, dict):
            out[key] = slim(value)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            out[key] = [slim(v) if isinstance(v, dict) else v for v in value[:8]]
        else:
            out[key] = value
    return out


def main() -> None:
    orders = RAW / "orders.jsonl"
    sent = []
    other = []
    with orders.open(encoding="utf-8") as handle:
        for line in handle:
            if not any(n in line.lower() for n in NEEDLES):
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            event = str(row.get("event") or "")
            if event == "sent" or event == "flatten" or "fill" in event:
                sent.append(slim(row))
            elif event in KEEP_EVENTS and event not in {"claim", "skip"}:
                other.append(slim(row))
            elif event in {"claim", "skip"}:
                continue
            else:
                other.append(slim(row))

    kalshi_fills = {}
    kalshi_http = {}
    for ticker in TICKERS:
        try:
            rows = rec.fetch_kalshi_fills(ticker, pages=3)
        except Exception as exc:
            kalshi_http[ticker] = f"{type(exc).__name__}"
            kalshi_fills[ticker] = []
            continue
        kalshi_http[ticker] = "ok"
        kalshi_fills[ticker] = [slim(r) for r in rows[:20]]

    kalshi_pos = []
    try:
        status, text = kalshi_private.signed_call(
            "GET",
            "/trade-api/v2/portfolio/positions",
            query={"limit": "200", "count_filter": "position"},
            timeout=20,
        )
        data = json.loads(text) if text else {}
        markets = data.get("market_positions") or data.get("positions") or []
        for row in markets if isinstance(markets, list) else []:
            blob = json.dumps(row, default=str).lower()
            if any(n in blob for n in NEEDLES) or "abohar" in blob:
                kalshi_pos.append(slim(row))
        kalshi_pos_n = len(markets) if isinstance(markets, list) else -1
        kalshi_pos_http = status
    except Exception as exc:
        kalshi_pos_http = f"{type(exc).__name__}"
        kalshi_pos_n = -1

    poly_trades = []
    poly_http = ""
    try:
        poly_trades = [slim(r) for r in rec.fetch_poly_trades(SLUG, pages=3)]
        poly_http = "ok"
    except Exception as exc:
        poly_http = type(exc).__name__

    poly_all = []
    try:
        status, text = polymarket_us_live.get_activities(
            {
                "limit": "50",
                "types": "ACTIVITY_TYPE_TRADE",
                "sortOrder": "SORT_ORDER_DESCENDING",
            },
            timeout=20,
        )
        data = json.loads(text) if text else {}
        acts = data.get("activities") or []
        for row in acts if isinstance(acts, list) else []:
            blob = json.dumps(row, default=str).lower()
            if any(n in blob for n in NEEDLES):
                poly_all.append(slim(row))
        poly_act_http = status
        poly_act_n = len(acts) if isinstance(acts, list) else -1
    except Exception as exc:
        poly_act_http = type(exc).__name__
        poly_act_n = -1

    cache = {}
    dash = RAW / "dashboard_cache.json"
    if dash.exists():
        blob = json.loads(dash.read_text(encoding="utf-8"))
        cache = {
            "n_open": len(blob.get("open_rows") or []),
            "open_rows": [
                {
                    "system": r.get("system") or r.get("letter"),
                    "type": r.get("type") or r.get("kind"),
                    "game": r.get("game") or r.get("instrument"),
                    "sport": r.get("sport"),
                    "league": r.get("league"),
                    "bet_for": r.get("bet_for") or r.get("side"),
                    "venue": r.get("venue"),
                    "qty": r.get("qty"),
                    "exposure": r.get("exposure") or r.get("cash"),
                    "hold": r.get("hold_class") or r.get("hold"),
                    "instrument": r.get("instrument") or r.get("ticker") or r.get("slug"),
                }
                for r in (blob.get("open_rows") or [])
            ],
        }

    venue_cache = json.loads((RAW / "open_count_venue_cache.json").read_text(encoding="utf-8"))
    out = {
        "at": datetime.now(ET).isoformat(timespec="seconds"),
        "n_sent_like": len(sent),
        "sent": sent[-40:],
        "n_other": len(other),
        "other_tail": other[-20:],
        "kalshi_http": kalshi_http,
        "kalshi_fills": kalshi_fills,
        "kalshi_pos_http": kalshi_pos_http,
        "kalshi_pos_n": kalshi_pos_n,
        "kalshi_pos_aboian": kalshi_pos,
        "poly_http": poly_http,
        "poly_trades": poly_trades,
        "poly_act_http": poly_act_http,
        "poly_act_n": poly_act_n,
        "poly_act_hits": poly_all,
        "dashboard": cache,
        "venue_kalshi": venue_cache.get("kalshi"),
        "venue_poly": venue_cache.get("poly"),
    }
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT} sent={len(sent)} other={len(other)} kalshi_fills={[len(v) for v in kalshi_fills.values()]} poly={len(poly_trades)}")


if __name__ == "__main__":
    main()
