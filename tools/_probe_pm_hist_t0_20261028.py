"""Probe Kalshi + Polymarket public sports history. No secrets. No orders."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prediction_paths import LOCAL_STAMP

UA = {
    "User-Agent": "Mozilla/5.0 stockresearch-pm-hist-probe/1.0",
    "Accept": "application/json",
}
KBASE = "https://api.elections.kalshi.com/trade-api/v2"
GBASE = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
OUT = LOCAL_STAMP / "hist" / "probe"


def http(url: str, tries: int = 4) -> tuple[int, object]:
    delay = 1.5
    last_code = 0
    last_body: object = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    return resp.status, json.loads(raw)
                except json.JSONDecodeError:
                    return resp.status, raw[:400]
        except urllib.error.HTTPError as exc:
            last_code = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            try:
                last_body = json.loads(raw) if raw else {"error": str(exc)}
            except json.JSONDecodeError:
                last_body = raw[:400]
            if exc.code == 429 and attempt < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            return last_code, last_body
        except Exception as exc:
            last_code = 0
            last_body = {"error": type(exc).__name__, "msg": str(exc)[:200]}
            if attempt < tries - 1:
                time.sleep(delay)
                continue
            return last_code, last_body
    return last_code, last_body


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {}

    code, cutoff = http(KBASE + "/historical/cutoff")
    report["kalshi_cutoff"] = {"http": code, "body": cutoff}
    print(f"kalshi cutoff {code}", flush=True)

    series_rows = []
    for cat in ("Sports", "sports", "Sport", ""):
        q = {}
        if cat:
            q["category"] = cat
        url = KBASE + "/series" + (("?" + urllib.parse.urlencode(q)) if q else "")
        code, body = http(url)
        n = 0
        if isinstance(body, dict):
            n = len(body.get("series") or [])
        report[f"kalshi_series_cat_{cat or 'all'}"] = {"http": code, "n": n}
        print(f"kalshi series category={cat or 'ALL'} http={code} n={n}", flush=True)
        if isinstance(body, dict) and body.get("series"):
            series_rows.extend(body["series"])
            (OUT / f"kalshi_series_{cat or 'all'}.json").write_text(
                json.dumps(body, indent=2)[:2_000_000], encoding="utf-8"
            )
            if cat == "Sports" or n > 50:
                break
        time.sleep(0.2)

    tickers = []
    for row in series_rows:
        if isinstance(row, dict) and row.get("ticker"):
            tickers.append(row)
    (OUT / "kalshi_series_flat.json").write_text(
        json.dumps(
            [
                {
                    "ticker": r.get("ticker"),
                    "title": r.get("title"),
                    "category": r.get("category"),
                    "categories": r.get("categories"),
                    "tags": r.get("tags"),
                    "frequency": r.get("frequency"),
                }
                for r in tickers
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"kalshi series unique listed {len(tickers)}", flush=True)
    report["kalshi_series_n"] = len(tickers)
    report["kalshi_series_tickers"] = [r.get("ticker") for r in tickers]

    sample_series = [
        "KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL",
        "KXNCAAFGAME", "KXATPMATCH", "KXNBAGAME", "KXNHLGAME",
    ]
    for series in sample_series:
        q = urllib.parse.urlencode({
            "series_ticker": series,
            "status": "settled",
            "limit": "3",
            "with_nested_markets": "true",
        })
        code, body = http(KBASE + "/events?" + q)
        events = (body or {}).get("events") if isinstance(body, dict) else []
        n_mkt = 0
        first = events[0] if events else {}
        if isinstance(first, dict):
            n_mkt = len(first.get("markets") or [])
        report[f"events_{series}"] = {
            "http": code,
            "n_events": len(events) if isinstance(events, list) else 0,
            "nested_markets_first": n_mkt,
            "first_ticker": (first or {}).get("event_ticker"),
            "cursor": (body or {}).get("cursor") if isinstance(body, dict) else None,
        }
        print(
            f"  events {series} http={code} n={len(events) if isinstance(events, list) else 0} "
            f"nested0={n_mkt} { (first or {}).get('event_ticker') }",
            flush=True,
        )
        time.sleep(0.15)

    # Sample NFL game candles if we have an event
    nfl = report.get("events_KXNFLGAME") or {}
    eticker = nfl.get("first_ticker")
    if eticker:
        code, body = http(
            KBASE + "/markets?" + urllib.parse.urlencode({"event_ticker": eticker, "limit": "20"})
        )
        mkts = (body or {}).get("markets") if isinstance(body, dict) else []
        report["nfl_markets"] = {
            "http": code,
            "n": len(mkts) if isinstance(mkts, list) else 0,
            "sample": [
                {
                    "ticker": m.get("ticker"),
                    "result": m.get("result"),
                    "status": m.get("status"),
                    "occurrence_datetime": m.get("occurrence_datetime"),
                    "expected_expiration_time": m.get("expected_expiration_time"),
                    "yes_sub_title": m.get("yes_sub_title"),
                    "floor_strike": m.get("floor_strike"),
                    "settled_time": m.get("settled_time") or m.get("close_time"),
                }
                for m in (mkts or [])[:6] if isinstance(m, dict)
            ],
        }
        print(f"  nfl markets http={code} n={report['nfl_markets']['n']}", flush=True)
        if mkts:
            m0 = mkts[0]
            occ = m0.get("occurrence_datetime") or m0.get("expected_expiration_time")
            ticker = m0.get("ticker")
            series = str(eticker).split("-", 1)[0]
            if occ and ticker:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromisoformat(str(occ).replace("Z", "+00:00"))
                    t0 = int(dt.timestamp())
                except Exception:
                    t0 = int(time.time()) - 86400
                q = urllib.parse.urlencode({
                    "start_ts": t0 - 30 * 60,
                    "end_ts": t0 + 60,
                    "period_interval": 1,
                    "include_latest_before_start": "true",
                })
                live_url = f"{KBASE}/series/{series}/markets/{urllib.parse.quote(ticker)}/candlesticks?{q}"
                hcode, hbody = http(live_url)
                n_c = 0
                if isinstance(hbody, dict):
                    n_c = len(hbody.get("candlesticks") or [])
                report["candle_live"] = {"http": hcode, "n": n_c, "url": live_url, "sample": None}
                if isinstance(hbody, dict) and hbody.get("candlesticks"):
                    report["candle_live"]["sample"] = (hbody.get("candlesticks") or [])[:2]
                    (OUT / "kalshi_candle_live_sample.json").write_text(
                        json.dumps(hbody)[:200000], encoding="utf-8"
                    )
                print(f"  live 1m candles http={hcode} n={n_c}", flush=True)
                hist_url = f"{KBASE}/historical/markets/{urllib.parse.quote(ticker)}/candlesticks?{q}"
                hcode2, hbody2 = http(hist_url)
                n_c2 = 0
                if isinstance(hbody2, dict):
                    n_c2 = len(hbody2.get("candlesticks") or [])
                report["candle_hist"] = {"http": hcode2, "n": n_c2}
                print(f"  hist 1m candles http={hcode2} n={n_c2}", flush=True)
                time.sleep(0.2)

    # Historical markets for an older event: page settled NFL until we find one with empty nested
    q = urllib.parse.urlencode({
        "series_ticker": "KXNFLGAME",
        "status": "settled",
        "limit": "200",
        "with_nested_markets": "true",
    })
    code, body = http(KBASE + "/events?" + q)
    events = (body or {}).get("events") if isinstance(body, dict) else []
    old = None
    for ev in events or []:
        if isinstance(ev, dict) and not (ev.get("markets") or []):
            old = ev
            break
    if not old and events:
        old = events[-1]
    if old:
        et = old.get("event_ticker")
        hcode, hbody = http(
            KBASE + "/historical/markets?" + urllib.parse.urlencode({"event_ticker": et, "limit": "20"})
        )
        hm = (hbody or {}).get("markets") if isinstance(hbody, dict) else []
        report["hist_markets"] = {
            "http": hcode,
            "event": et,
            "n": len(hm) if isinstance(hm, list) else 0,
            "sample": [
                {
                    "ticker": m.get("ticker"),
                    "result": m.get("result"),
                    "occurrence_datetime": m.get("occurrence_datetime"),
                    "expected_expiration_time": m.get("expected_expiration_time"),
                }
                for m in (hm or [])[:4] if isinstance(m, dict)
            ],
        }
        print(f"  hist markets {et} http={hcode} n={report['hist_markets']['n']}", flush=True)

    # Polymarket
    for path, name in (
        ("/sports", "poly_sports"),
        ("/series?limit=100", "poly_series"),
        ("/tags?limit=100", "poly_tags"),
    ):
        code, body = http(GBASE + path)
        n = len(body) if isinstance(body, list) else (len((body or {}).get("series") or []) if isinstance(body, dict) else 0)
        report[name] = {"http": code, "n": n, "type": type(body).__name__}
        (OUT / f"{name}.json").write_text(json.dumps(body, indent=2)[:1_500_000], encoding="utf-8")
        print(f"{name} http={code} n={n}", flush=True)
        time.sleep(0.15)

    code, body = http(GBASE + "/events?series_id=12185&closed=true&limit=2")
    evs = body if isinstance(body, list) else (body or {}).get("events") if isinstance(body, dict) else []
    report["poly_nfl_events"] = {"http": code, "n": len(evs) if isinstance(evs, list) else 0}
    print(f"poly nfl series 12185 closed http={code} n={report['poly_nfl_events']['n']}", flush=True)
    if isinstance(evs, list) and evs:
        ev = evs[0] if isinstance(evs[0], dict) else {}
        mkts = ev.get("markets") or []
        report["poly_nfl_event0"] = {
            "id": ev.get("id"),
            "slug": ev.get("slug"),
            "title": ev.get("title"),
            "startDate": ev.get("startDate") or ev.get("start_date"),
            "n_markets": len(mkts),
            "market0_keys": sorted((mkts[0] or {}).keys()) if mkts and isinstance(mkts[0], dict) else [],
            "market0": {
                k: (mkts[0] or {}).get(k)
                for k in (
                    "question", "slug", "sportsMarketType", "marketType", "groupItemTitle",
                    "outcomes", "outcomePrices", "clobTokenIds", "line", "spread",
                    "closed", "umaResolutionStatus",
                )
            } if mkts else {},
        }
        (OUT / "poly_nfl_event0.json").write_text(json.dumps(ev)[:400000], encoding="utf-8")
        print(
            f"  poly event {ev.get('slug')} markets={len(mkts)} "
            f"type0={report['poly_nfl_event0']['market0'].get('sportsMarketType')}",
            flush=True,
        )
        token = None
        if mkts and isinstance(mkts[0], dict):
            toks = mkts[0].get("clobTokenIds")
            if isinstance(toks, str):
                try:
                    toks = json.loads(toks)
                except json.JSONDecodeError:
                    toks = []
            if isinstance(toks, list) and toks:
                token = toks[0]
        start = ev.get("startDate") or ev.get("start_date") or ""
        t0 = None
        if start:
            from datetime import datetime
            try:
                t0 = int(datetime.fromisoformat(str(start).replace("Z", "+00:00")).timestamp())
            except Exception:
                t0 = None
        if token and t0:
            q = urllib.parse.urlencode({
                "market": token,
                "startTs": t0 - 3600,
                "endTs": t0 + 120,
                "fidelity": 1,
            })
            hcode, hbody = http(CLOB + "/prices-history?" + q)
            hist = (hbody or {}).get("history") if isinstance(hbody, dict) else None
            n_h = len(hist) if isinstance(hist, list) else 0
            report["poly_prices"] = {"http": hcode, "n": n_h, "sample": (hist or [])[-3:] if hist else None}
            print(f"  poly prices-history 1m http={hcode} n={n_h}", flush=True)

    (OUT / "probe_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT / 'probe_report.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
