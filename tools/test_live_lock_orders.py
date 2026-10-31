"""Rules for the one-contract lock orders. No network. No secrets."""
from decimal import Decimal, ROUND_CEILING

import json

import gemini_private
import kalshi_private
import live_lock_orders
import orders_performance_refresh
import venue_fill_confirm

orders_performance_refresh.run_rebuild = lambda: ""
live_lock_orders._MARKET_SIZE_FETCH_ENABLED = False
# Unit tests exercise send math. Live systems.json may have lock.off.
live_lock_orders.lock_system_on = lambda: True


def _pin_balances(amount):
    from datetime import datetime
    import time
    from zoneinfo import ZoneInfo

    import venue_cash_local

    saved = (
        dict(live_lock_orders._venue_balances),
        live_lock_orders._balances_seeded,
        live_lock_orders._balances_at,
        dict(live_lock_orders._venue_balance_live_at),
        venue_cash_local.CASH_FILE,
    )
    venue_cash_local.reset_for_tests()
    live_lock_orders._balances_seeded = True
    live_lock_orders._balances_at = datetime.max.replace(tzinfo=ZoneInfo("America/New_York"))
    live_lock_orders._venue_balances.clear()
    live_lock_orders._venue_balance_live_at.clear()
    if amount is not None:
        now = time.time()
        for venue in ("kalshi", "gemini", "polymarket"):
            live_lock_orders._venue_balances[venue] = Decimal(amount)
            live_lock_orders._venue_balance_live_at[venue] = now
    return saved


def _unpin_balances(saved) -> None:
    import venue_cash_local

    balances, seeded, stamp, live_at, cash_file = saved
    live_lock_orders._venue_balances.clear()
    live_lock_orders._venue_balances.update(balances)
    live_lock_orders._balances_seeded = seeded
    live_lock_orders._balances_at = stamp
    live_lock_orders._venue_balance_live_at.clear()
    live_lock_orders._venue_balance_live_at.update(live_at)
    venue_cash_local.CASH_FILE = cash_file


class Scan:
    def gemini_fee(self, price: Decimal) -> Decimal:
        raw = Decimal("0.07") * price * (Decimal("1") - price)
        if raw < 0:
            raw = Decimal("0")
        return raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING)

    def gemini_no_rejection(self, cand: dict):
        if cand.get("no_flipped_yes_bid"):
            return "flipped Yes bid"
        return None

    def _trade_bet_key(self, sport, game, cand):
        return "bet"


def _pair(**extra):
    row = {
        "market_type": "spread",
        "side": "Tennessee",
        "number": "3.5",
        "yes_venue": "kalshi",
        "no_venue": "gemini",
        "yes_price": "0.40",
        "no_price": "0.53",
        "yes_size": "2",
        "no_size": "2",
        "kalshi_ticker": "KX-TEST",
        "gemini_symbol": "GEMI-TEST",
        "no_flipped_yes_bid": False,
    }
    row.update(extra)
    return row


def test_net_at_095_qualifies():
    cand = _pair()
    net = live_lock_orders.pair_net(Scan(), cand)
    kfee = live_lock_orders.kalshi_fee_amount(Decimal("0.40"))
    gfee = Scan().gemini_fee(Decimal("0.53"))
    assert kfee == Decimal("0.0168")
    assert net == Decimal("0.40") + Decimal("0.53") + kfee + gfee
    ok, reason = live_lock_orders.qualifies(Scan(), cand, "Some Game", {})
    assert ok, reason
    assert live_lock_orders._net_text(net) in reason


def test_net_above_095_stays_alert_only():
    ok, reason = live_lock_orders.qualifies(Scan(), _pair(no_price="0.58"), "Some Game", {})
    assert not ok
    line = live_lock_orders.send_line()
    assert f"above {line}" in reason


def test_hair_over_net_max_skip_shows_unrounded_cost():
    class FineFee(Scan):
        def gemini_fee(self, price: Decimal) -> Decimal:
            return Decimal("0.02001")

    old = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.97")
        line = live_lock_orders.send_line()
        assert line == format(live_lock_orders.NET_MAX, "f")
        hair_cand = _pair(no_price="0.55")
        hair_net = live_lock_orders.pair_net(FineFee(), hair_cand)
        kfee = live_lock_orders.kalshi_fee_amount(Decimal("0.40"))
        assert hair_net == Decimal("0.40") + Decimal("0.55") + Decimal("0.02001") + kfee
        ok, reason = live_lock_orders.qualifies(
            FineFee(), hair_cand, "Some Game", {}
        )
        assert not ok
        assert live_lock_orders._net_text(hair_net) in reason
        assert f"{line} is above {line}" not in reason
        assert reason == f"net {live_lock_orders._net_text(hair_net)} is above {line}"

        at_cap, at_reason = live_lock_orders.qualifies(
            Scan(), _pair(no_price="0.53"), "Some Game", {}
        )
        assert at_cap, at_reason

        import opportunity_considerations

        hair = Decimal("0.97001")
        text = opportunity_considerations.gate_denial(
            _pair(no_price="0.55"), "Some Game", hair
        )
        assert text == (
            f"After-fee cost {opportunity_considerations._fmt(hair)} is above the {line} send line "
            "but still at or under 0.99."
        )
        assert f"{line} is above the {line} send line" not in text
        mapped = opportunity_considerations.reason_from_qualifies(
            reason, _pair(no_price="0.55"), hair
        )
        assert mapped == text
        moved = (
            f"Price moved. After-fee cost {live_lock_orders._net_text(hair)} "
            f"is above the {line} send line but still at or under 0.99."
        )
        assert "0.97001" in moved
        assert f"{line} is above the {line} send line" not in moved
    finally:
        live_lock_orders.NET_MAX = old


def test_opportunity_skip_reason_uses_live_net_max():
    import opportunity_considerations

    line = live_lock_orders.send_line()
    cap = live_lock_orders.effective_net_max()
    over = min(cap + Decimal("0.01"), Decimal("0.99"))
    if over > cap:
        text = opportunity_considerations.gate_denial(_pair(no_price="0.56"), "Some Game", over)
        assert text == (
            f"After-fee cost {opportunity_considerations._fmt(over)} is above the {line} send line "
            "but still at or under 0.99."
        )
        mapped = opportunity_considerations.reason_from_qualifies(
            f"net {format(over, 'f')} is above {line}", _pair(no_price="0.56"), over
        )
        assert line in mapped and "0.95 send line" not in mapped
    else:
        text = opportunity_considerations.gate_denial(_pair(), "Some Game", cap)
        assert text == ""
        assert opportunity_considerations.logged_net(_pair(), Decimal("0.991")) is None
    old_mapped = opportunity_considerations.reason_from_qualifies(
        "net 0.97 is above 0.95", _pair(no_price="0.55"), Decimal("0.97")
    )
    shown = opportunity_considerations._display_reason(
        "After-fee cost 0.97 is above the 0.95 send line but still at or under 0.99."
    )
    if Decimal("0.97") > cap:
        assert f"above the {line} send line" in old_mapped
        assert f"above the {line} send line" in shown
        assert "0.95 send line" not in shown
    else:
        assert f"above the {line} send line" not in old_mapped
        assert f"above the {line} send line" not in shown
    assert "0.99" in shown


def test_leg_deny_reason_names_missing_fields():
    why = live_lock_orders._leg_deny_reason(
        {"yes_venue": "kalshi", "yes_price": "0.40", "no_venue": "kalshi", "no_price": "0.50"},
        "yes",
    )
    assert "kalshi_ticker" in why
    assert "Missing order fields for yes (kalshi)" in why
    why2 = live_lock_orders._leg_deny_reason(
        {"yes_venue": "polymarket", "yes_price": "0.40", "polymarket_slug": "abc"},
        "yes",
    )
    assert "polymarket_intent" in why2
    why3 = live_lock_orders._leg_deny_reason(
        {"yes_venue": "gemini", "yes_price": "0.40"},
        "yes",
    )
    assert "gemini_symbol" in why3
    why4 = live_lock_orders._leg_deny_reason({"yes_price": "0.40"}, "yes")
    assert "yes_venue" in why4


def test_display_rewrites_old_missing_order_fields():
    import opportunity_considerations

    shown = opportunity_considerations._missing_fields_display(
        {"yes_venue": "polymarket", "no_venue": "novig", "reason": "Missing order fields."},
        "Missing order fields.",
    )
    assert "polymarket/novig" in shown
    assert "not the catalog scan" in shown
    assert shown != "Missing order fields."
    named = opportunity_considerations._missing_fields_display(
        {},
        "Missing order fields for yes (kalshi): kalshi_ticker.",
    )
    assert named == "Missing order fields for yes (kalshi): kalshi_ticker."


def test_catalog_eligible_reason_is_not_a_send_deny():
    import opportunity_considerations

    old = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.98")
        text = opportunity_considerations.catalog_eligible_reason(Decimal("0.93"))
        assert "This is the catalog scan; it never sends." in text
        assert "Live pollers send when after-fee cost is at or under 0.98 (from NET_MAX)." in text
        assert "After-fee cost on this look is 0.9300." in text
        assert "at or under the 0.98 send line" not in text
        assert opportunity_considerations.gate_denial(
            _pair(yes_venue="novig", no_venue="gemini", yes_price="0.29", no_price="0.61"),
            "New Mexico State vs Sam Houston",
            Decimal("0.93"),
        ) == ""
        shown = opportunity_considerations._display_reason(
            "After-fee cost 0.93 is at or under the 0.98 send line. This catalog pass does not send orders."
        )
        assert shown == text
        live_lock_orders.NET_MAX = Decimal("0.96")
        moved = opportunity_considerations.catalog_eligible_reason(Decimal("0.93"))
        assert "0.96" in moved
        assert "0.98" not in moved
        rewritten = opportunity_considerations._display_reason(
            "After-fee cost 0.93 is at or under the 0.95 send line. This catalog pass does not send orders."
        )
        assert rewritten == moved
    finally:
        live_lock_orders.NET_MAX = old


def test_record_catalog_logs_eligible_quote_as_catalog_only():
    import opportunity_considerations

    seen = []

    def fake_record(sport, game, cand, decision, reason, net=None, at=None):
        seen.append((sport, game, decision, reason, net, cand.get("yes_size")))
        return True

    old_record = opportunity_considerations.record
    old_max = live_lock_orders.NET_MAX
    old_verify = opportunity_considerations._should_catalog_verify
    try:
        live_lock_orders.NET_MAX = Decimal("0.98")
        opportunity_considerations.record = fake_record
        opportunity_considerations._should_catalog_verify = lambda *a, **k: False
        ready = _pair(
            yes_venue="novig",
            no_venue="gemini",
            yes_price="0.29",
            no_price="0.61",
            yes_size="350",
            no_size="290",
            net="0.93",
            side="NMSU",
            number="7.5",
        )
        missing = dict(ready)
        missing["yes_size"] = "0"
        opportunity_considerations.record_catalog(
            "college football",
            "New Mexico State vs Sam Houston",
            [ready, missing],
        )
        assert len(seen) == 2
        assert seen[0][2] == "denied"
        assert seen[0][4] == Decimal("0.93")
        assert "This is the catalog scan; it never sends." in seen[0][3]
        assert "at or under the 0.98 send line" not in seen[0][3]
        assert live_lock_orders.send_line() in seen[0][3]
        assert seen[1][3] == "Missing size."
    finally:
        opportunity_considerations.record = old_record
        opportunity_considerations._should_catalog_verify = old_verify
        live_lock_orders.NET_MAX = old_max


def test_fmt_after_fee_cost_is_at_least_four_decimals():
    import opportunity_considerations

    assert opportunity_considerations._fmt(Decimal("0.98")) == "0.9800"
    assert opportunity_considerations._fmt(Decimal("0.98414")) == "0.98414"
    assert opportunity_considerations._fmt(Decimal("0.98399")) == "0.98399"
    assert opportunity_considerations._fmt(Decimal("0.98399")) != "0.98"
    assert opportunity_considerations._fmt(Decimal("0.99")) == "0.9900"
    assert opportunity_considerations._fmt(Decimal("0.9862")) == "0.9862"
    assert live_lock_orders._net_text(Decimal("0.98399")) == "0.98399"
    assert live_lock_orders._net_text(Decimal("0.98399")) != "0.98"
    assert live_lock_orders._net_text(Decimal("0.99")) == "0.9900"
    assert live_lock_orders._net_text(Decimal("0.9862")) == "0.9862"


def test_qualifies_compares_unrounded_decimal_not_round2():
    import inspect

    src = inspect.getsource(live_lock_orders.qualifies)
    assert "round(net" not in src
    assert "net > effective_net_max()" in src
    block = inspect.getsource(live_lock_orders._profit_block)
    assert "round(net" not in block
    assert "net > effective_net_max()" in block
    leftover = inspect.getsource(live_lock_orders._rank_qualifying_opposites)
    assert "net > cap" in leftover
    pair = inspect.getsource(live_lock_orders.pair_net)
    assert "quantize" not in pair
    assert "round(" not in pair


def test_cap_099_sends_0986_denies_0991():
    old = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.99")
        assert live_lock_orders.effective_net_max() == Decimal("0.99")
        under = _pair(no_venue="kalshi", no_price="0.5519")
        net = live_lock_orders.pair_net(Scan(), under)
        assert net == Decimal("0.9860")
        assert not (net > live_lock_orders.effective_net_max())
        ok, reason = live_lock_orders.qualifies(Scan(), under, "Some Game", {})
        assert ok, reason
        assert "0.9860" in reason
        over = _pair(no_venue="kalshi", no_price="0.5569")
        over_net = live_lock_orders.pair_net(Scan(), over)
        assert over_net == Decimal("0.9910")
        assert over_net > live_lock_orders.effective_net_max()
        bad, bad_reason = live_lock_orders.qualifies(Scan(), over, "Some Game", {})
        assert not bad
        assert "0.9910" in bad_reason
        assert f"above {live_lock_orders.send_line()}" in bad_reason
    finally:
        live_lock_orders.NET_MAX = old


def test_opportunities_row_display_is_four_decimals():
    import opportunity_considerations

    exact = {
        "at": "2026-10-25T13:00:00-04:00",
        "sport": "tennis",
        "game": "A vs B",
        "market_type": "moneyline",
        "side": "A",
        "number": "",
        "yes_venue": "kalshi",
        "no_venue": "kalshi",
        "yes_price": "0.4775",
        "no_price": "0.4775",
        "yes_size": "2",
        "no_size": "2",
        "net": "0.99",
        "decision": "denied",
        "reason": "catalog",
    }
    html = opportunity_considerations._cells(exact)
    assert "0.9900" in html
    assert ">0.99<" not in html
    cand = _nmsu_under_send_line()
    cand.update({
        "at": "2026-10-25T13:00:00-04:00",
        "sport": "college football",
        "game": "New Mexico State vs Sam Houston",
        "decision": "denied",
        "reason": "catalog",
        "net": "0.98",
    })
    shown = opportunity_considerations._cells(cand)
    nmsu_net = live_lock_orders.pair_net(Scan(), cand)
    assert nmsu_net is not None
    assert opportunity_considerations._fmt(nmsu_net) in shown
    assert ">0.98<" not in shown
    assert opportunity_considerations._fmt(nmsu_net) != "0.98"


def test_catalog_recomputes_rounded_net_before_send_compare():
    """Catalog money() 0.98 is not the compared value. SF 10.5 Novig+Kalshi is 0.98414 > 0.984."""
    import opportunity_considerations

    seen = []

    def fake_record(sport, game, cand, decision, reason, net=None, at=None):
        seen.append((decision, reason, net, cand.get("source"), cand.get("trigger_source")))
        return True

    old_record = opportunity_considerations.record
    old_max = live_lock_orders.NET_MAX
    old_verify = opportunity_considerations._should_catalog_verify
    try:
        live_lock_orders.NET_MAX = Decimal("0.9839")
        opportunity_considerations.record = fake_record
        opportunity_considerations._should_catalog_verify = lambda *a, **k: False
        cand = _pair(
            market_type="spread",
            side="SF",
            number="10.5",
            yes_venue="novig",
            no_venue="kalshi",
            yes_price="0.38",
            no_price="0.5729",
            yes_size="3736",
            no_size="5322",
            net="0.98",
            fee_coefficient="0.06",
            fee_charged="WHEN_LIVE",
            event_status="OPEN_INGAME",
        )
        opportunity_considerations.record_catalog(
            "pro football",
            "San Francisco vs Atlanta",
            [cand],
        )
        assert len(seen) == 1
        decision, reason, net, source, trigger = seen[0]
        assert decision == "denied"
        kfee = live_lock_orders.kalshi_fee_amount(Decimal("0.5729"))
        novig_fee = Decimal("0.01414")
        assert net == Decimal("0.38") + Decimal("0.5729") + novig_fee + kfee
        assert net == Decimal("0.98414")
        assert net > live_lock_orders.effective_net_max()
        assert live_lock_orders._net_text(net) in reason
        assert f"above the {live_lock_orders.send_line()} send line" in reason
        assert "0.98 is above" not in reason
        assert source == "catalog scan"
        assert trigger == "catalog scan"
        shown = opportunity_considerations._display_reason(
            "This is the catalog scan; it never sends. "
            "Live pollers send when after-fee cost is at or under 0.984 (from NET_MAX). "
            "After-fee cost on this look is 0.98.",
            Decimal("0.98414"),
        )
        assert "0.98414" in shown
        assert f"above the {live_lock_orders.send_line()} send line" in shown
        assert "catalog scan" in shown.lower()
    finally:
        opportunity_considerations.record = old_record
        opportunity_considerations._should_catalog_verify = old_verify
        live_lock_orders.NET_MAX = old_max


def test_catalog_verify_second_row_still_gap():
    import opportunity_considerations

    seen = []

    def fake_record(sport, game, cand, decision, reason, net=None, at=None):
        seen.append((decision, reason, net, cand.get("source"), cand.get("trigger_source"), cand.get("yes_price"), cand.get("no_price")))
        return True

    def fake_live(spec, *, pace=True):
        live = dict(spec)
        if spec.get("outcome") == "yes":
            live["pay"] = "0.29"
            live["quote_size"] = "10"
        else:
            live["pay"] = "0.61"
            live["quote_size"] = "8"
        return "", live

    old_record = opportunity_considerations.record
    old_live = live_lock_orders._live_from_book
    old_max = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.99")
        opportunity_considerations.record = fake_record
        live_lock_orders._live_from_book = fake_live
        cand = _pair(
            yes_venue="kalshi",
            no_venue="gemini",
            yes_price="0.29",
            no_price="0.61",
            yes_size="350",
            no_size="290",
            net="0.93",
        )
        opportunity_considerations.record_catalog(
            "college football",
            "New Mexico State vs Sam Houston",
            [cand],
        )
        assert len(seen) == 2
        assert seen[0][3] == "catalog scan"
        assert "This is the catalog scan; it never sends." in seen[0][1]
        assert seen[1][3] == "catalog verify"
        assert seen[1][4] == "REST recheck"
        assert seen[1][0] == "denied"
        assert "still a gap" in seen[1][1]
        assert "Catalog still does not send" in seen[1][1]
        assert "live poller may" in seen[1][1]
        assert "0.99" in seen[1][1]
        assert seen[1][2] is not None
        assert seen[1][2] <= Decimal("0.99")
        assert opportunity_considerations._fmt(seen[1][2]).count(".") == 1
        assert len(opportunity_considerations._fmt(seen[1][2]).split(".")[1]) >= 4
    finally:
        opportunity_considerations.record = old_record
        live_lock_orders._live_from_book = old_live
        live_lock_orders.NET_MAX = old_max


def test_catalog_verify_second_row_gap_closed():
    import opportunity_considerations

    seen = []

    def fake_record(sport, game, cand, decision, reason, net=None, at=None):
        seen.append((decision, reason, net, cand.get("source"), cand.get("yes_price"), cand.get("no_price")))
        return True

    def fake_live(spec, *, pace=True):
        live = dict(spec)
        if spec.get("outcome") == "yes":
            live["pay"] = "0.50"
            live["quote_size"] = "3"
        else:
            live["pay"] = "0.55"
            live["quote_size"] = "4"
        return "", live

    old_record = opportunity_considerations.record
    old_live = live_lock_orders._live_from_book
    old_max = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.99")
        opportunity_considerations.record = fake_record
        live_lock_orders._live_from_book = fake_live
        cand = _pair(
            yes_venue="kalshi",
            no_venue="kalshi",
            yes_price="0.40",
            no_price="0.53",
            yes_size="2",
            no_size="2",
            net="0.93",
            kalshi_ticker="KX-TEST",
        )
        opportunity_considerations.record_catalog("tennis", "A vs B", [cand])
        assert len(seen) == 2
        assert seen[0][3] == "catalog scan"
        assert seen[1][3] == "catalog verify"
        assert seen[1][4] == "0.50"
        assert seen[1][5] == "0.55"
        closed_net = (
            Decimal("0.50")
            + Decimal("0.55")
            + live_lock_orders.kalshi_fee_amount(Decimal("0.50"))
            + live_lock_orders.kalshi_fee_amount(Decimal("0.55"))
        )
        assert seen[1][2] == closed_net
        assert "no longer a gap" in seen[1][1]
        assert live_lock_orders._net_text(closed_net) in seen[1][1]
        assert "vs cap 0.99" in seen[1][1]
        assert "was catalog" in seen[1][1]
        assert "Catalog still does not send" in seen[1][1]
        shown = opportunity_considerations._display_reason(seen[1][1], seen[1][2])
        assert "no longer a gap" in shown
        assert "still at or under 0.99" not in shown
        assert opportunity_considerations.logged_net(
            {"source": "catalog verify", "net": "1.05"}, Decimal("1.05")
        ) == Decimal("1.05")
    finally:
        opportunity_considerations.record = old_record
        live_lock_orders._live_from_book = old_live
        live_lock_orders.NET_MAX = old_max


def test_catalog_verify_429_named_no_retry():
    import opportunity_considerations

    seen = []

    def fake_record(sport, game, cand, decision, reason, net=None, at=None):
        seen.append(reason)
        return True

    calls = {"n": 0}

    def fake_live(spec, *, pace=True):
        calls["n"] += 1
        venue = spec.get("venue") or "book"
        return f"{venue} book empty (book http 429)", None

    old_record = opportunity_considerations.record
    old_live = live_lock_orders._live_from_book
    try:
        opportunity_considerations.record = fake_record
        live_lock_orders._live_from_book = fake_live
        cand = _pair(
            yes_venue="kalshi",
            no_venue="gemini",
            yes_price="0.40",
            no_price="0.53",
            yes_size="2",
            no_size="2",
            net="0.95",
        )
        opportunity_considerations.record_catalog("tennis", "A vs B", [cand])
        assert len(seen) == 2
        assert "429" in seen[1]
        assert "Did not retry" in seen[1]
        assert "Catalog still does not send" in seen[1]
        assert calls["n"] == 2
    finally:
        opportunity_considerations.record = old_record
        live_lock_orders._live_from_book = old_live


def test_catalog_verify_missing_fields_named():
    import opportunity_considerations

    seen = []

    def fake_record(sport, game, cand, decision, reason, net=None, at=None):
        seen.append((cand.get("source"), reason))
        return True

    old_record = opportunity_considerations.record
    old_live = live_lock_orders._live_from_book
    try:
        opportunity_considerations.record = fake_record
        live_lock_orders._live_from_book = lambda spec, **_k: (_ for _ in ()).throw(AssertionError("no GET if fields missing"))
        cand = _pair(
            yes_venue="kalshi",
            no_venue="gemini",
            yes_price="0.40",
            no_price="0.53",
            yes_size="2",
            no_size="2",
            net="0.95",
        )
        cand.pop("kalshi_ticker")
        cand.pop("gemini_symbol")
        opportunity_considerations.record_catalog("tennis", "A vs B", [cand])
        assert len(seen) == 2
        assert seen[1][0] == "catalog verify"
        assert "missing fields" in seen[1][1].lower()
        assert "kalshi_ticker" in seen[1][1]
        assert "gemini_symbol" in seen[1][1]
        assert "Catalog still does not send" in seen[1][1]
    finally:
        opportunity_considerations.record = old_record
        live_lock_orders._live_from_book = old_live


def test_catalog_verify_never_posts_orders():
    import inspect

    import opportunity_considerations
    from prediction_paths import DRIVE_STAMP

    rec = inspect.getsource(opportunity_considerations.record_catalog)
    maybe = inspect.getsource(opportunity_considerations._maybe_catalog_execute)
    chk = inspect.getsource(opportunity_considerations._catalog_rest_recheck)
    begin = inspect.getsource(opportunity_considerations._begin_catalog_recheck)
    finish = inspect.getsource(opportunity_considerations._finish_catalog_recheck)
    scan = (DRIVE_STAMP / "overnight_scan.py").read_text(encoding="utf-8")
    assert "execute_locks" in rec
    assert "skip_book_recheck=True" in maybe
    assert rec.find("_begin_catalog_recheck") < rec.find("record(sport, game, use")
    assert "execute_locks" not in chk
    assert "execute_locks" not in begin
    assert "execute_locks" not in finish
    assert "execute_locks" not in scan
    assert "Public GETs only. No orders." in scan[:500]
    assert "_live_from_book" in begin
    assert "pace=False" in begin
    assert "place_order" not in begin.lower()
    assert "_post(" not in begin
    assert "_post(" not in chk


def test_catalog_verify_recheck_is_parallel():
    import time

    import opportunity_considerations

    seen = []
    starts = []

    def fake_record(sport, game, cand, decision, reason, net=None, at=None):
        seen.append(cand.get("source"))
        return True

    def fake_live(spec, *, pace=True):
        assert pace is False
        starts.append(time.perf_counter())
        time.sleep(0.2)
        live = dict(spec)
        live["pay"] = "0.50" if spec.get("outcome") == "yes" else "0.55"
        live["quote_size"] = "2"
        return "", live

    old_record = opportunity_considerations.record
    old_live = live_lock_orders._live_from_book
    old_max = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.99")
        opportunity_considerations.record = fake_record
        live_lock_orders._live_from_book = fake_live
        t0 = time.perf_counter()
        opportunity_considerations.record_catalog(
            "tennis",
            "A vs B",
            [_pair(yes_price="0.40", no_price="0.53", net="0.95")],
        )
        elapsed = time.perf_counter() - t0
        assert seen == ["catalog scan", "catalog verify"]
        assert len(starts) == 2
        assert abs(starts[0] - starts[1]) < 0.12
        assert elapsed < 0.45
    finally:
        opportunity_considerations.record = old_record
        live_lock_orders._live_from_book = old_live
        live_lock_orders.NET_MAX = old_max


def test_catalog_verify_hands_books_to_execute_when_still_gap():
    import opportunity_considerations

    seen = []
    sent = []

    def fake_record(sport, game, cand, decision, reason, net=None, at=None):
        seen.append((cand.get("source"), reason, decision))
        return True

    def fake_live(spec, *, pace=True):
        live = dict(spec)
        live["pay"] = "0.29" if spec.get("outcome") == "yes" else "0.61"
        live["quote_size"] = "10"
        return "", live

    def fake_execute(*_a, **kwargs):
        sent.append(kwargs.get("skip_book_recheck"))

    old_record = opportunity_considerations.record
    old_live = live_lock_orders._live_from_book
    old_exec = live_lock_orders.execute_locks
    old_max = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.99")
        opportunity_considerations.record = fake_record
        live_lock_orders._live_from_book = fake_live
        live_lock_orders.execute_locks = fake_execute
        cand = _pair(
            yes_venue="kalshi",
            no_venue="gemini",
            yes_price="0.29",
            no_price="0.61",
            yes_size="350",
            no_size="290",
            net="0.93",
        )
        opportunity_considerations.record_catalog(
            "college football",
            "Atlanta vs Tampa Bay",
            [cand],
            game_row={"date": "2026-10-26", "codes": ["ATL", "TB"]},
            scan=Scan(),
            log=lambda *_a, **_k: None,
        )
        assert sent == [True]
        assert seen[0][0] == "catalog scan"
        assert seen[1][0] == "catalog verify"
        assert "Handed REST books" in seen[1][1]
        assert "no second book GET" in seen[1][1]
        opportunity_considerations.record_catalog(
            "college football",
            "Atlanta vs Tampa Bay",
            [cand],
        )
        assert sent == [True]
    finally:
        opportunity_considerations.record = old_record
        live_lock_orders._live_from_book = old_live
        live_lock_orders.execute_locks = old_exec
        live_lock_orders.NET_MAX = old_max


def test_catalog_verify_does_not_execute_when_gap_closed():
    import opportunity_considerations

    sent = []

    def fake_record(sport, game, cand, decision, reason, net=None, at=None):
        return True

    def fake_live(spec, *, pace=True):
        live = dict(spec)
        live["pay"] = "0.50" if spec.get("outcome") == "yes" else "0.55"
        live["quote_size"] = "3"
        return "", live

    old_record = opportunity_considerations.record
    old_live = live_lock_orders._live_from_book
    old_exec = live_lock_orders.execute_locks
    old_max = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.99")
        opportunity_considerations.record = fake_record
        live_lock_orders._live_from_book = fake_live
        live_lock_orders.execute_locks = lambda *_a, **_k: sent.append(1)
        opportunity_considerations.record_catalog(
            "tennis",
            "A vs B",
            [_pair(yes_price="0.40", no_price="0.53", net="0.93", kalshi_ticker="KX-TEST")],
            game_row={},
            scan=Scan(),
        )
        assert sent == []
    finally:
        opportunity_considerations.record = old_record
        live_lock_orders._live_from_book = old_live
        live_lock_orders.execute_locks = old_exec
        live_lock_orders.NET_MAX = old_max


def test_recheck_pair_books_is_parallel_and_skips_pace():
    import time

    starts = []

    def fake_live(spec, *, pace=True):
        assert pace is False
        starts.append(time.perf_counter())
        time.sleep(0.2)
        live = dict(spec)
        live["pay"] = spec.get("pay") or "0.40"
        live["quote_size"] = "10"
        return "", live

    old_live = live_lock_orders._live_from_book
    old_block = live_lock_orders._profit_block
    try:
        live_lock_orders._live_from_book = fake_live
        live_lock_orders._profit_block = lambda *_a, **_k: ""
        a = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "instrument": "KX"}
        b = {"venue": "novig", "outcome": "no", "pay": "0.50", "instrument": "N"}
        t0 = time.perf_counter()
        gate, live_a, live_b = live_lock_orders._recheck_pair_books(a, b)
        elapsed = time.perf_counter() - t0
        assert gate == ""
        assert live_a is not None and live_b is not None
        assert len(starts) == 2
        assert abs(starts[0] - starts[1]) < 0.12
        assert elapsed < 0.45
    finally:
        live_lock_orders._live_from_book = old_live
        live_lock_orders._profit_block = old_block


def test_recheck_over_cap_reason_names_both_rest_sizes():
    """Over-cap skip keeps REST sizes so the No size at the recheck ask is not blank."""

    def fake_live(spec, *, pace=True):
        live = dict(spec)
        if spec.get("venue") == "kalshi":
            live["pay"] = "0.68"
            live["quote_size"] = "27351.52"
        else:
            live["pay"] = "0.33"
            live["quote_size"] = "37676.90"
        return "", live

    old_live = live_lock_orders._live_from_book
    try:
        live_lock_orders._live_from_book = fake_live
        a = {"venue": "kalshi", "outcome": "yes", "pay": "0.67", "instrument": "VIR"}
        b = {
            "venue": "gemini",
            "outcome": "no",
            "pay": "0.29",
            "instrument": "g",
        }
        gate, live_a, live_b = live_lock_orders._recheck_pair_books(a, b)
        assert gate.startswith("over cap after book recheck")
        assert "limit=0.68" in gate
        assert "other=0.33" in gate
        assert "limit_size=27351.52" in gate
        assert "other_size=37676.90" in gate
        assert "limit_venue=kalshi" in gate
        assert "other_venue=gemini" in gate
        assert live_a is not None and live_b is not None
        assert live_a.get("quote_size") == "27351.52"
        assert live_b.get("quote_size") == "37676.90"
    finally:
        live_lock_orders._live_from_book = old_live


def test_send_pair_skip_book_recheck_does_not_fetch():
    pair_gets = []

    def boom(*_a, **_k):
        pair_gets.append(1)
        raise AssertionError("second book GET")

    old_pair = live_lock_orders._recheck_pair_books
    old_spec = live_lock_orders._spec_at_price
    old_funds = live_lock_orders._funds_block
    old_profit = live_lock_orders._profit_block
    old_ioc = live_lock_orders._one_ioc
    old_live = live_lock_orders._live_from_book
    old_pages = live_lock_orders._refresh_order_pages
    old_consider = live_lock_orders._log_consider
    old_append = live_lock_orders._append
    try:
        live_lock_orders._recheck_pair_books = boom
        live_lock_orders._spec_at_price = lambda spec, pay: dict(spec, pay=str(pay), limit=str(pay), body={"price": str(pay)})
        live_lock_orders._funds_block = lambda _b: ""
        live_lock_orders._profit_block = lambda *_a, **_k: ""
        live_lock_orders._live_from_book = lambda spec, **_k: ("", dict(spec))
        live_lock_orders._one_ioc = lambda *_a, **_k: {
            "filled": False, "payload": None, "status": 0, "note": "not posted",
            "pay": "0.40", "spec": {}, "step": "hard", "posted": False,
        }
        live_lock_orders._refresh_order_pages = lambda: None
        live_lock_orders._log_consider = lambda *_a, **_k: None
        live_lock_orders._append = lambda *_a, **_k: None
        kalshi = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "instrument": "KX", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.40", "quote_size": "10"}
        gemini = {"venue": "gemini", "outcome": "no", "pay": "0.50", "instrument": "G", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.50", "quote_size": "8"}
        live_lock_orders._send_pair(lambda *_a, **_k: None, "k", "Game", [kalshi, gemini], skip_book_recheck=True)
        assert pair_gets == []
    finally:
        live_lock_orders._recheck_pair_books = old_pair
        live_lock_orders._spec_at_price = old_spec
        live_lock_orders._funds_block = old_funds
        live_lock_orders._profit_block = old_profit
        live_lock_orders._one_ioc = old_ioc
        live_lock_orders._live_from_book = old_live
        live_lock_orders._refresh_order_pages = old_pages
        live_lock_orders._log_consider = old_consider
        live_lock_orders._append = old_append


def test_net_max_full_precision_accepts_0983_rejects_105():
    import tempfile
    from pathlib import Path

    import prediction_systems

    old_path = prediction_systems.CONFIG_PATH
    prediction_systems.CONFIG_PATH = Path(tempfile.mkdtemp()) / "systems.json"
    try:
        _assert_net_max_full_precision_default()
    finally:
        prediction_systems.CONFIG_PATH = old_path


def _assert_net_max_full_precision_default():
    assert live_lock_orders.NET_MAX == Decimal("0.984")
    cap = live_lock_orders.effective_net_max()
    assert cap == Decimal("0.984")
    under = _pair(no_venue="kalshi", no_price="0.5489")
    net = live_lock_orders.pair_net(Scan(), under)
    assert net == Decimal("0.9830")
    # Rounding the cap to 2dp would make 0.98 and skip 0.983.
    assert net > cap.quantize(Decimal("0.01"))
    assert not (net > cap)
    ok, reason = live_lock_orders.qualifies(Scan(), under, "Some Game", {})
    assert ok, reason
    over = _pair(no_venue="kalshi", no_price="0.65")
    over_net = live_lock_orders.pair_net(Scan(), over)
    kfee_yes = live_lock_orders.kalshi_fee_amount(Decimal("0.40"))
    kfee_no = live_lock_orders.kalshi_fee_amount(Decimal("0.65"))
    assert over_net == Decimal("0.40") + Decimal("0.65") + kfee_yes + kfee_no
    assert over_net > Decimal("1")
    bad, bad_reason = live_lock_orders.qualifies(Scan(), over, "Some Game", {})
    assert not bad
    assert live_lock_orders._net_text(over_net) in bad_reason


def test_send_line_copy_follows_net_max():
    old = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.97")
        assert live_lock_orders.send_line() == "0.97"
        text = live_lock_orders.rewrite_send_line_copy(
            "After-fee cost 0.98 is above the 0.95 send line but still at or under 0.99."
        )
        assert text == "After-fee cost 0.98 is above the 0.97 send line but still at or under 0.99."
        assert live_lock_orders.rewrite_send_line_copy("1 contract when net <= 0.95") == (
            "1 contract when net <= 0.97"
        )
        assert live_lock_orders.rewrite_send_line_copy("net 0.98 is above 0.96") == (
            "net 0.98 is above 0.97"
        )
    finally:
        live_lock_orders.NET_MAX = old


def _nmsu_under_send_line(**extra):
    row = _pair(
        market_type="spread",
        side="New Mexico St. wins by over 9.5 points",
        number="9.5",
        yes_venue="kalshi",
        no_venue="novig",
        yes_price="0.34",
        no_price="0.614",
        yes_size="2564.12",
        no_size="2579.64",
        kalshi_ticker="KX-NMSU",
        fee_coefficient="0.06",
        fee_charged="ALWAYS",
        no_flipped_yes_bid=False,
    )
    row.update(extra)
    return row


def test_unrounded_cost_under_send_line_is_not_printed_as_above():
    import opportunity_considerations

    old = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.9841")
        line = live_lock_orders.send_line()
        cap = live_lock_orders.effective_net_max()
        assert line == format(cap, "f")
        cand = _nmsu_under_send_line()
        net = live_lock_orders.pair_net(Scan(), cand)
        cost = net
        assert cost is not None
        assert cost < cap
        assert cost > Decimal("0.34") + Decimal("0.614")
        assert net == cost
        ok, reason = live_lock_orders.qualifies(
            Scan(), cand, "New Mexico State vs Sam Houston", {}
        )
        assert ok, reason
        assert "above" not in reason
        denial = opportunity_considerations.gate_denial(
            cand, "New Mexico State vs Sam Houston", cost
        )
        assert denial == ""
        stale = (
            f"After-fee cost {format(cost, 'f')} is above the 0.982 send line "
            "but still at or under 0.99."
        )
        rewritten = live_lock_orders.rewrite_send_line_copy(stale)
        assert f"above the {line} send line" not in rewritten
        assert format(cost, "f") in rewritten
        assert live_lock_orders.rewrite_send_line_copy(
            f"net {format(cost, 'f')} is above 0.982"
        ) == f"net {format(cost, 'f')} is above 0.982"
        mapped = opportunity_considerations.reason_from_qualifies(
            f"net {format(cost, 'f')} is above 0.982", cand, cost
        )
        assert f"above the {line} send line" not in mapped
        shown = opportunity_considerations._display_reason(stale)
        assert f"above the {line} send line" not in shown
        over = cap + Decimal("0.00001")
        over_text = live_lock_orders.rewrite_send_line_copy(
            f"After-fee cost {format(over, 'f')} is above the 0.982 send line "
            "but still at or under 0.99."
        )
        assert over_text == (
            f"After-fee cost {format(over, 'f')} is above the {line} send line "
            "but still at or under 0.99."
        )
    finally:
        live_lock_orders.NET_MAX = old


def test_execute_locks_sends_when_unrounded_cost_is_under_send_line():
    class DummyLock:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    dummy_yes = {
        "venue": "kalshi",
        "instrument": "KX-NMSU",
        "outcome": "yes",
        "pay": "0.34",
        "limit": "0.34",
        "body": {},
        "intent": "",
    }
    dummy_no = {
        "venue": "novig",
        "instrument": "N",
        "outcome": "no",
        "pay": "0.63",
        "limit": "0.63",
        "body": {},
        "intent": "",
    }
    saved = (
        live_lock_orders._leg_spec,
        live_lock_orders._capability_ok,
        live_lock_orders._affordable,
        live_lock_orders._preview,
        live_lock_orders._read_balances,
        live_lock_orders.ensure_venue_balance,
        live_lock_orders.venue_pace.FileLock,
        live_lock_orders._read_orders,
        live_lock_orders.bet_blocked,
        live_lock_orders._append_unlocked,
        live_lock_orders._send_pair,
        live_lock_orders.open_lock_keys,
        live_lock_orders.strategy_b_blocks_lock,
        live_lock_orders.orders_halted,
        live_lock_orders.watch_is_active,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders._log_consider,
        live_lock_orders.NET_MAX,
        live_lock_orders.lock_system_on,
    )
    sent = []
    live_lock_orders._leg_spec = lambda _cand, outcome: dummy_yes if outcome == "yes" else dummy_no
    live_lock_orders._capability_ok = lambda *_a, **_k: (True, "")
    live_lock_orders._affordable = lambda *_a, **_k: True
    live_lock_orders._preview = lambda *_a, **_k: (True, "ok")
    live_lock_orders._read_balances = lambda: {"kalshi": Decimal("10"), "novig": Decimal("10")}
    live_lock_orders.ensure_venue_balance = lambda *_a, **_k: None
    live_lock_orders.venue_pace.FileLock = DummyLock
    live_lock_orders._read_orders = lambda: []
    live_lock_orders.bet_blocked = lambda *_a, **_k: False
    live_lock_orders._append_unlocked = lambda *_a, **_k: None
    live_lock_orders._send_pair = lambda *_a, **_k: sent.append("send")
    live_lock_orders.open_lock_keys = lambda *_a, **_k: []
    live_lock_orders.strategy_b_blocks_lock = lambda *_a, **_k: False
    live_lock_orders.orders_halted = lambda: False
    live_lock_orders.watch_is_active = lambda *_a, **_k: False
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders._log_consider = lambda *_a, **_k: None
    live_lock_orders.lock_system_on = lambda: True
    try:
        live_lock_orders.NET_MAX = Decimal("0.9841")
        live_lock_orders.execute_locks(
            Scan(),
            "college football",
            "New Mexico State vs Sam Houston",
            {},
            {"candidates": [_nmsu_under_send_line()]},
            [],
            lambda *_a, **_k: None,
        )
        assert sent == ["send"]
    finally:
        live_lock_orders._leg_spec = saved[0]
        live_lock_orders._capability_ok = saved[1]
        live_lock_orders._affordable = saved[2]
        live_lock_orders._preview = saved[3]
        live_lock_orders._read_balances = saved[4]
        live_lock_orders.ensure_venue_balance = saved[5]
        live_lock_orders.venue_pace.FileLock = saved[6]
        live_lock_orders._read_orders = saved[7]
        live_lock_orders.bet_blocked = saved[8]
        live_lock_orders._append_unlocked = saved[9]
        live_lock_orders._send_pair = saved[10]
        live_lock_orders.open_lock_keys = saved[11]
        live_lock_orders.strategy_b_blocks_lock = saved[12]
        live_lock_orders.orders_halted = saved[13]
        live_lock_orders.watch_is_active = saved[14]
        live_lock_orders.ORDERS_ENABLED = saved[15]
        live_lock_orders._log_consider = saved[16]
        live_lock_orders.NET_MAX = saved[17]
        live_lock_orders.lock_system_on = saved[18]


def test_size_cap_needs_one_whole_contract():
    ok, _reason = live_lock_orders.qualifies(Scan(), _pair(yes_size="0.5"), "Some Game", {})
    assert not ok


def test_tennessee_13_5_is_blocked():
    cand = _pair(number="13.5", side="Tennessee", market_type="spread")
    ok, reason = live_lock_orders.qualifies(Scan(), cand, "Tennessee vs Indianapolis", {"title_kalshi": "Tennessee vs Indianapolis"})
    assert not ok
    assert "Tennessee" in reason


def test_flipped_gemini_no_is_blocked():
    ok, _reason = live_lock_orders.qualifies(Scan(), _pair(no_flipped_yes_bid=True), "Some Game", {})
    assert not ok


def test_missing_moves_send_kalshi_first():
    order = live_lock_orders.ordered_outcomes(_pair(), [])
    assert order == ["yes", "no"]
    fresh = [
        {"venue": "Gemini", "pay": "no", "market_type": "spread", "number": "3.5", "move": "0.20"},
        {"venue": "Kalshi", "pay": "yes", "market_type": "spread", "number": "3.5", "move": "-0.04"},
    ]
    assert live_lock_orders.ordered_outcomes(_pair(), fresh) == ["no", "yes"]


def test_kalshi_no_is_a_yes_ask_at_one_minus_price():
    body = live_lock_orders.kalshi_order_body("KX-TEST", "no", Decimal("0.40"), "cid")
    assert body["side"] == "ask"
    assert body["price"] == "0.6000"
    assert body["count"] == "1.00"
    assert body["time_in_force"] == "immediate_or_cancel"
    yes = live_lock_orders.kalshi_order_body("KX-TEST", "yes", Decimal("0.40"), "cid")
    assert yes["side"] == "bid"
    assert yes["price"] == "0.4000"


def test_polymarket_short_price_does_not_pay_more():
    price = live_lock_orders.polymarket_api_price("ORDER_INTENT_BUY_SHORT", Decimal("0.830"))
    assert price == Decimal("0.170")
    long_price = live_lock_orders.polymarket_api_price("ORDER_INTENT_BUY_LONG", Decimal("0.8314"))
    assert long_price == Decimal("0.831")


def test_open_lock_keys_counts_live_true_locks_not_flatten_or_history():
    live_titles = {"new mexico state vs sam houston"}
    live_codes = {("nmsushsu", "2026-10-21")}
    nmsu = "college football\tnmsushsu\t2026-10-21\ttotal\tover\t27.5\tkalshi\tnovig"
    nmsu2 = "college football\tnmsushsu\t2026-10-21\tspread\tcode:SHSU\t9.5\tkalshi\tgemini"
    nmsu3 = "college football\tnmsushsu\t2026-10-21\ttotal\tover\t47.5\tkalshi\tnovig"
    old = "pro football\tcarphi\t2026-10-18\ttotal\tover\t40.5\tkalshi\tgemini"
    b_key = "tennis-b\tcasbue\tTaverna vs Bueno\tkalshi\tTaverna\tt0"
    flat = "college football\tnmsushsu\t2026-10-21\tmoneyline\tcode:NMSU\t\tkalshi\tgemini"
    rows = [
        {"event": "claim", "bet_key": nmsu, "game": "New Mexico State vs Sam Houston", "pid": 1},
        {"event": "sent", "bet_key": nmsu},
        {"event": "filled", "bet_key": nmsu},
        {"event": "filled", "bet_key": nmsu},
        {"event": "claim", "bet_key": nmsu2, "game": "New Mexico State vs Sam Houston", "pid": 1},
        {"event": "sent", "bet_key": nmsu2},
        {"event": "filled", "bet_key": nmsu2},
        {"event": "one_leg", "bet_key": nmsu2},
        {"event": "claim", "bet_key": nmsu3, "game": "New Mexico State vs Sam Houston", "pid": 1},
        {"event": "sent", "bet_key": nmsu3},
        {"event": "filled", "bet_key": nmsu3},
        {"event": "filled", "bet_key": nmsu3},
        {"event": "claim", "bet_key": old, "game": "Carolina vs Philadelphia", "pid": 1},
        {"event": "sent", "bet_key": old},
        {"event": "filled", "bet_key": old},
        {"event": "one_leg", "bet_key": old},
        {"event": "claim", "bet_key": b_key, "game": "Taverna vs Bueno", "pid": 1},
        {"event": "sent", "bet_key": b_key},
        {"event": "filled", "bet_key": b_key},
        {"event": "claim", "bet_key": flat, "game": "New Mexico State vs Sam Houston", "pid": 1},
        {"event": "sent", "bet_key": flat},
        {"event": "filled", "bet_key": flat},
        {"event": "flatten_filled", "bet_key": flat, "game": "New Mexico State vs Sam Houston"},
    ]
    keys = live_lock_orders.open_lock_keys(
        rows,
        pid_alive=lambda _pid: False,
        live_titles=live_titles,
        live_codes=live_codes,
        watches=[],
        include_watches=True,
        overlay=False,
    )
    assert live_lock_orders.MAX_OPEN_LOCKS == 3
    assert nmsu in keys
    assert nmsu2 in keys
    assert nmsu3 in keys
    assert old not in keys
    assert b_key not in keys
    assert flat not in keys
    assert live_lock_orders.lock_slots_full(keys)
    leftover = "college football\tnmsushsu\t2026-10-21\ttotal\tover\t31.5\tkalshi\tgemini"
    assert leftover in live_lock_orders.open_lock_keys(
        rows,
        pid_alive=lambda _pid: False,
        live_titles=set(),
        live_codes=set(),
        watches=[{"bet_key": leftover, "filled_venue": "kalshi", "stopped": False}],
        include_watches=True,
        overlay=False,
    )


def test_open_lock_keys_ignores_dead_claims_and_unfilled_sends():
    live_titles = {"new mexico state vs sam houston"}
    live_codes = {("nmsushsu", "2026-10-21")}
    shsu_gemini = "college football\tnmsushsu\t2026-10-21\tspread\tcode:SHSU\t2.5\tgemini\tkalshi"
    shsu_novig = "college football\tnmsushsu\t2026-10-21\tspread\tcode:SHSU\t2.5\tkalshi\tnovig"
    over_novig = "college football\tnmsushsu\t2026-10-21\ttotal\tover\t33.5\tkalshi\tnovig"
    nmsu_novig = "college football\tnmsushsu\t2026-10-21\tspread\tcode:NMSU\t5.5\tkalshi\tnovig"
    sent_miss = "college football\tnmsushsu\t2026-10-21\ttotal\tover\t27.5\tkalshi\tgemini"
    inflight = "college football\tnmsushsu\t2026-10-21\tspread\tcode:NMSU\t1.5\tkalshi\tgemini"
    empty_watch = "college football\tnmsushsu\t2026-10-21\ttotal\tover\t29.5\tkalshi\tnovig"
    rows = [
        {"event": "claim", "bet_key": shsu_gemini, "game": "New Mexico State vs Sam Houston", "pid": 12616},
        {"event": "claim", "bet_key": shsu_novig, "game": "New Mexico State vs Sam Houston", "pid": 40680},
        {"event": "claim", "bet_key": over_novig, "game": "New Mexico State vs Sam Houston", "pid": 32316},
        {"event": "skip", "bet_key": over_novig},
        {"event": "claim", "bet_key": over_novig, "game": "New Mexico State vs Sam Houston", "pid": 32316},
        {"event": "claim", "bet_key": nmsu_novig, "game": "New Mexico State vs Sam Houston", "pid": 29208},
        {"event": "claim", "bet_key": sent_miss, "game": "New Mexico State vs Sam Houston", "pid": 44104},
        {"event": "sent", "bet_key": sent_miss, "venue": "kalshi"},
        {"event": "both_unfilled", "bet_key": sent_miss, "venue": "kalshi", "other_venue": "gemini"},
        {"event": "claim", "bet_key": inflight, "game": "New Mexico State vs Sam Houston", "pid": 44104},
    ]
    reused = live_lock_orders.open_lock_keys(
        rows,
        pid_alive=lambda pid: pid in (29208, 44104),
        live_titles=live_titles,
        live_codes=live_codes,
        watches=[{"bet_key": empty_watch, "stopped": False}],
        include_watches=True,
        poller_pids={"new mexico state vs sam houston": 44104, "nmsushsu|2026-10-21": 44104},
        overlay=False,
    )
    assert shsu_gemini not in reused
    assert shsu_novig not in reused
    assert over_novig not in reused
    assert nmsu_novig not in reused
    assert sent_miss not in reused
    assert empty_watch not in reused
    assert inflight in reused
    assert not live_lock_orders.lock_slots_full(reused)


def test_execute_locks_skips_when_open_lock_cap_hit():
    saved = (
        live_lock_orders.open_lock_keys,
        live_lock_orders._send_pair,
        live_lock_orders.strategy_b_blocks_lock,
        live_lock_orders.orders_halted,
        live_lock_orders.watch_is_active,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders._log_consider,
        live_lock_orders.lock_system_on,
    )
    seen = []
    live_lock_orders.open_lock_keys = lambda *_a, **_k: ["a", "b", "c"]
    live_lock_orders._send_pair = lambda *_a, **_k: seen.append("send")
    live_lock_orders.strategy_b_blocks_lock = lambda *_a, **_k: False
    live_lock_orders.orders_halted = lambda: False
    live_lock_orders.watch_is_active = lambda *_a, **_k: False
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders._log_consider = lambda decision, reason, *a, **k: seen.append(f"{decision}:{reason}")
    live_lock_orders.lock_system_on = lambda: True
    try:
        live_lock_orders.execute_locks(
            Scan(),
            "college football",
            "New Mexico State vs Sam Houston",
            {},
            {"candidates": [_pair(side="Sam Houston", number="9.5")]},
            [],
            lambda *_a, **_k: None,
        )
    finally:
        live_lock_orders.open_lock_keys = saved[0]
        live_lock_orders._send_pair = saved[1]
        live_lock_orders.strategy_b_blocks_lock = saved[2]
        live_lock_orders.orders_halted = saved[3]
        live_lock_orders.watch_is_active = saved[4]
        live_lock_orders.ORDERS_ENABLED = saved[5]
        live_lock_orders._log_consider = saved[6]
        live_lock_orders.lock_system_on = saved[7]
    assert "send" not in seen
    assert any("denied:" in row and "max_open_locks=3" in row for row in seen)


def _empty_ok_snap():
    import open_count_sync as ocs

    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    return snap


def test_house_three_open_venues_zero_allows_send():
    """House tape says 3 open lock pairs; venues 0 → cap must not block."""
    g1 = "pro football\ttbcar\t2026-10-25\tmoneyline\tcode:TB\t\tkalshi\tgemini"
    g2 = "pro football\tnyghou\t2026-10-25\tmoneyline\tcode:NYG\t\tkalshi\tgemini"
    g3 = "pro football\tbufkc\t2026-10-25\tmoneyline\tcode:BUF\t\tkalshi\tgemini"
    rows = [
        {"event": "claim", "bet_key": g1, "game": "Tampa Bay vs Carolina", "pid": 1},
        {"event": "sent", "bet_key": g1, "venue": "kalshi", "instrument": "KX-TBCAR", "http_status": 201, "confirm_qty": "0", "confirm_known": True},
        {"event": "filled", "bet_key": g1, "venue": "kalshi", "instrument": "KX-TBCAR", "confirm_qty": "0"},
        {"event": "claim", "bet_key": g2, "game": "New York G vs Houston", "pid": 1},
        {"event": "sent", "bet_key": g2, "venue": "kalshi", "instrument": "KX-NYGHOU"},
        {"event": "filled", "bet_key": g2, "venue": "kalshi", "instrument": "KX-NYGHOU"},
        {"event": "claim", "bet_key": g3, "game": "Buffalo vs Kansas City", "pid": 1},
        {"event": "one_leg", "bet_key": g3, "venue": "kalshi", "instrument": "KX-BUFKC"},
    ]
    live_titles = {"tampa bay vs carolina", "new york g vs houston", "buffalo vs kansas city"}
    live_codes = {("tbcar", "2026-10-25"), ("nyghou", "2026-10-25"), ("bufkc", "2026-10-25")}
    house = live_lock_orders.open_lock_keys(
        rows,
        pid_alive=lambda _pid: False,
        live_titles=live_titles,
        live_codes=live_codes,
        watches=[],
        overlay=False,
    )
    assert len(house) == 3, house
    assert live_lock_orders.lock_slots_full(house)
    snap = _empty_ok_snap()
    venue = live_lock_orders.open_lock_keys(
        rows,
        pid_alive=lambda _pid: False,
        live_titles=live_titles,
        live_codes=live_codes,
        watches=[],
        snapshot=snap,
        overlay=True,
    )
    assert venue == []
    assert not live_lock_orders.lock_slots_full(venue)

    class DummyLock:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    dummy_yes = {
        "venue": "kalshi",
        "instrument": "KX-TBCAR",
        "outcome": "yes",
        "pay": "0.34",
        "limit": "0.34",
        "body": {},
        "intent": "",
    }
    dummy_no = {
        "venue": "novig",
        "instrument": "N",
        "outcome": "no",
        "pay": "0.63",
        "limit": "0.63",
        "body": {},
        "intent": "",
    }
    saved = (
        live_lock_orders._LOCK_VENUE_SNAPSHOT,
        live_lock_orders._leg_spec,
        live_lock_orders._capability_ok,
        live_lock_orders._affordable,
        live_lock_orders._preview,
        live_lock_orders._read_balances,
        live_lock_orders.ensure_venue_balance,
        live_lock_orders.venue_pace.FileLock,
        live_lock_orders._read_orders,
        live_lock_orders.bet_blocked,
        live_lock_orders._append_unlocked,
        live_lock_orders._send_pair,
        live_lock_orders.strategy_b_blocks_lock,
        live_lock_orders.directional_blocks_lock,
        live_lock_orders.orders_halted,
        live_lock_orders.watch_is_active,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders._log_consider,
        live_lock_orders.NET_MAX,
        live_lock_orders.lock_system_on,
    )
    sent = []
    live_lock_orders._LOCK_VENUE_SNAPSHOT = snap
    live_lock_orders._leg_spec = lambda _cand, outcome: dummy_yes if outcome == "yes" else dummy_no
    live_lock_orders._capability_ok = lambda *_a, **_k: (True, "")
    live_lock_orders._affordable = lambda *_a, **_k: True
    live_lock_orders._preview = lambda *_a, **_k: (True, "ok")
    live_lock_orders._read_balances = lambda: {"kalshi": Decimal("10"), "novig": Decimal("10")}
    live_lock_orders.ensure_venue_balance = lambda *_a, **_k: None
    live_lock_orders.venue_pace.FileLock = DummyLock
    live_lock_orders._read_orders = lambda: rows
    live_lock_orders.bet_blocked = lambda *_a, **_k: False
    live_lock_orders._append_unlocked = lambda *_a, **_k: None
    live_lock_orders._send_pair = lambda *_a, **_k: sent.append("send")
    live_lock_orders.strategy_b_blocks_lock = lambda *_a, **_k: False
    live_lock_orders.directional_blocks_lock = lambda *_a, **_k: False
    live_lock_orders.orders_halted = lambda: False
    live_lock_orders.watch_is_active = lambda *_a, **_k: False
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders._log_consider = lambda *_a, **_k: None
    live_lock_orders.lock_system_on = lambda: True
    try:
        live_lock_orders.NET_MAX = Decimal("0.9841")
        live_lock_orders.execute_locks(
            Scan(),
            "pro football",
            "Tampa Bay vs Carolina",
            {},
            {"candidates": [_nmsu_under_send_line(side="Tampa Bay wins by over 9.5 points")]},
            [],
            lambda *_a, **_k: None,
        )
        assert sent == ["send"], sent
    finally:
        live_lock_orders._LOCK_VENUE_SNAPSHOT = saved[0]
        live_lock_orders._leg_spec = saved[1]
        live_lock_orders._capability_ok = saved[2]
        live_lock_orders._affordable = saved[3]
        live_lock_orders._preview = saved[4]
        live_lock_orders._read_balances = saved[5]
        live_lock_orders.ensure_venue_balance = saved[6]
        live_lock_orders.venue_pace.FileLock = saved[7]
        live_lock_orders._read_orders = saved[8]
        live_lock_orders.bet_blocked = saved[9]
        live_lock_orders._append_unlocked = saved[10]
        live_lock_orders._send_pair = saved[11]
        live_lock_orders.strategy_b_blocks_lock = saved[12]
        live_lock_orders.directional_blocks_lock = saved[13]
        live_lock_orders.orders_halted = saved[14]
        live_lock_orders.watch_is_active = saved[15]
        live_lock_orders.ORDERS_ENABLED = saved[16]
        live_lock_orders._log_consider = saved[17]
        live_lock_orders.NET_MAX = saved[18]
        live_lock_orders.lock_system_on = saved[19]
        live_lock_orders._clear_consider()


def test_execute_locks_denies_tbcar_nms_mix():
    """Game title Tampa Bay vs Carolina + New Mexico St. side is not a send."""
    class DummyLock:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    dummy_yes = {
        "venue": "kalshi",
        "instrument": "KX-TBCAR",
        "outcome": "yes",
        "pay": "0.34",
        "limit": "0.34",
        "body": {},
        "intent": "",
    }
    dummy_no = {
        "venue": "novig",
        "instrument": "N",
        "outcome": "no",
        "pay": "0.63",
        "limit": "0.63",
        "body": {},
        "intent": "",
    }
    saved = (
        live_lock_orders._LOCK_VENUE_SNAPSHOT,
        live_lock_orders._leg_spec,
        live_lock_orders._capability_ok,
        live_lock_orders._affordable,
        live_lock_orders._preview,
        live_lock_orders._read_balances,
        live_lock_orders.ensure_venue_balance,
        live_lock_orders.venue_pace.FileLock,
        live_lock_orders._read_orders,
        live_lock_orders.bet_blocked,
        live_lock_orders._append_unlocked,
        live_lock_orders._send_pair,
        live_lock_orders.strategy_b_blocks_lock,
        live_lock_orders.directional_blocks_lock,
        live_lock_orders.orders_halted,
        live_lock_orders.watch_is_active,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders._log_consider,
        live_lock_orders.NET_MAX,
        live_lock_orders.lock_system_on,
    )
    sent = []
    logged = []
    live_lock_orders._LOCK_VENUE_SNAPSHOT = _empty_ok_snap()
    live_lock_orders._leg_spec = lambda _cand, outcome: dummy_yes if outcome == "yes" else dummy_no
    live_lock_orders._capability_ok = lambda *_a, **_k: (True, "")
    live_lock_orders._affordable = lambda *_a, **_k: True
    live_lock_orders._preview = lambda *_a, **_k: (True, "ok")
    live_lock_orders._read_balances = lambda: {"kalshi": Decimal("10"), "novig": Decimal("10")}
    live_lock_orders.ensure_venue_balance = lambda *_a, **_k: None
    live_lock_orders.venue_pace.FileLock = DummyLock
    live_lock_orders._read_orders = lambda: []
    live_lock_orders.bet_blocked = lambda *_a, **_k: False
    live_lock_orders._append_unlocked = lambda *_a, **_k: None
    live_lock_orders._send_pair = lambda *_a, **_k: sent.append("send")
    live_lock_orders.strategy_b_blocks_lock = lambda *_a, **_k: False
    live_lock_orders.directional_blocks_lock = lambda *_a, **_k: False
    live_lock_orders.orders_halted = lambda: False
    live_lock_orders.watch_is_active = lambda *_a, **_k: False
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders._log_consider = lambda decision, reason, net=None, cand_patch=None: logged.append((decision, reason))
    live_lock_orders.lock_system_on = lambda: True
    try:
        live_lock_orders.NET_MAX = Decimal("0.9841")
        live_lock_orders.execute_locks(
            Scan(),
            "pro football",
            "Tampa Bay vs Carolina",
            {},
            {"candidates": [_nmsu_under_send_line()]},
            [],
            lambda *_a, **_k: None,
        )
        assert sent == [], sent
        assert logged
        assert logged[0][0] == "denied"
        assert "different events" in logged[0][1]
    finally:
        live_lock_orders._LOCK_VENUE_SNAPSHOT = saved[0]
        live_lock_orders._leg_spec = saved[1]
        live_lock_orders._capability_ok = saved[2]
        live_lock_orders._affordable = saved[3]
        live_lock_orders._preview = saved[4]
        live_lock_orders._read_balances = saved[5]
        live_lock_orders.ensure_venue_balance = saved[6]
        live_lock_orders.venue_pace.FileLock = saved[7]
        live_lock_orders._read_orders = saved[8]
        live_lock_orders.bet_blocked = saved[9]
        live_lock_orders._append_unlocked = saved[10]
        live_lock_orders._send_pair = saved[11]
        live_lock_orders.strategy_b_blocks_lock = saved[12]
        live_lock_orders.directional_blocks_lock = saved[13]
        live_lock_orders.orders_halted = saved[14]
        live_lock_orders.watch_is_active = saved[15]
        live_lock_orders.ORDERS_ENABLED = saved[16]
        live_lock_orders._log_consider = saved[17]
        live_lock_orders.NET_MAX = saved[18]
        live_lock_orders.lock_system_on = saved[19]
        live_lock_orders._clear_consider()


def test_bind_consider_drops_stale_tbcar_nms():
    live_lock_orders._set_consider(
        "pro football",
        "Tampa Bay vs Carolina",
        _nmsu_under_send_line(),
        Decimal("0.98392"),
    )
    kalshi = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "quote_size": "1"}
    poly = {"venue": "polymarket", "outcome": "no", "pay": "0.50", "quote_size": "1"}
    try:
        live_lock_orders._bind_consider_to_pair("Game", [kalshi, poly])
        cand = live_lock_orders._consider.cand
        assert live_lock_orders._consider.title == "Game"
        assert "New Mexico" not in str(cand.get("side") or "")
        assert cand.get("yes_venue") == "kalshi"
        assert cand.get("no_venue") == "polymarket"
        assert not live_lock_orders.pair_labels_conflict(
            live_lock_orders._consider.title, str(cand.get("side") or "")
        )
    finally:
        live_lock_orders._clear_consider()


def test_tape_filled_qty_ignores_book_qtydecimal():
    import venue_fill_confirm

    nested = {"status": "resting", "qtyDecimal": "2564.12", "asks": [{"qtyDecimal": "1"}]}
    assert venue_fill_confirm.tape_filled_qty(nested) == Decimal("0")
    assert live_lock_orders.filled_contracts(nested) == Decimal("0")
    empty = {"status": "cancelled", "fill_count": "0.00"}
    assert venue_fill_confirm.tape_filled_qty(empty) == Decimal("0")
    assert live_lock_orders.filled_contracts(empty) == Decimal("0")
    with_id = {"id": "OID1", "cumQuantity": "1", "book": {"qtyDecimal": "50"}}
    assert venue_fill_confirm.tape_filled_qty(with_id) == Decimal("1")
    line = live_lock_orders.format_posted_leg_return({
        "status": 201,
        "posted": True,
        "payload": nested,
        "spec": {"venue": "kalshi", "outcome": "yes", "instrument": "KX"},
        "note": "ok",
    })
    assert "fill 0" in line
    assert "fill 1" not in line


def test_open_lock_keys_unique_games_venue_qty():
    key_a = "college football\tnmsushsu\t2026-10-21\ttotal\tover\t27.5\tkalshi\tnovig"
    key_b = "college football\tnmsushsu\t2026-10-21\tspread\tcode:SHSU\t9.5\tkalshi\tgemini"
    rows = [
        {"event": "filled", "bet_key": key_a, "game": "New Mexico State vs Sam Houston", "venue": "kalshi", "instrument": "KX-NMSU-27", "confirm_qty": "1"},
        {"event": "filled", "bet_key": key_a, "game": "New Mexico State vs Sam Houston", "venue": "novig", "instrument": "NV-NMSU-27", "confirm_qty": "1"},
        {"event": "one_leg", "bet_key": key_b, "game": "New Mexico State vs Sam Houston", "venue": "kalshi", "instrument": "KX-NMSU-95", "confirm_qty": "1"},
    ]
    snap = _empty_ok_snap()
    snap["kalshi"] = [
        {"venue": "kalshi", "ticker": "KX-NMSU-27", "qty": "1"},
        {"venue": "kalshi", "ticker": "KX-NMSU-95", "qty": "1"},
    ]
    snap["kalshi_by_ticker"] = {row["ticker"]: row for row in snap["kalshi"]}
    keys = live_lock_orders.open_lock_keys(
        rows,
        live_titles={"new mexico state vs sam houston"},
        live_codes={("nmsushsu", "2026-10-21")},
        watches=[],
        snapshot=snap,
    )
    assert len(keys) == 1, keys
    assert live_lock_orders.lock_game_id(keys[0]) == "nmsushsu|2026-10-21"
    assert not live_lock_orders.lock_slots_full(keys)


def test_open_lock_keys_drops_claims_empty_201_flattened_settled():
    claim = "pro football\ttbcar\t2026-10-25\tmoneyline\tcode:TB\t\tkalshi\tgemini"
    empty = "pro football\tnyghou\t2026-10-25\tmoneyline\tcode:NYG\t\tkalshi\tgemini"
    flat = "pro football\tbufkc\t2026-10-25\tmoneyline\tcode:BUF\t\tkalshi\tgemini"
    settled = "tennis\toldm\t2026-10-20\tmoneyline\tcode:OLD\t\tkalshi\tpolymarket"
    leftover = "pro football\tlacden\t2026-10-25\tmoneyline\tcode:LAC\t\tkalshi\tgemini"
    rows = [
        {"event": "claim", "bet_key": claim, "game": "Tampa Bay vs Carolina", "pid": 9},
        {"event": "sent", "bet_key": empty, "venue": "kalshi", "instrument": "KX-EMPTY", "http_status": 201, "confirm_qty": "0", "confirm_known": True},
        {"event": "filled", "bet_key": empty, "venue": "kalshi", "instrument": "KX-EMPTY", "confirm_qty": "0"},
        {"event": "filled", "bet_key": flat, "game": "Buffalo vs Kansas City", "venue": "kalshi", "instrument": "KX-FLAT", "confirm_qty": "1"},
        {"event": "flatten_filled", "bet_key": flat, "venue": "kalshi", "instrument": "KX-FLAT"},
        {"event": "filled", "bet_key": settled, "game": "Old vs Match", "venue": "kalshi", "instrument": "KX-SETTLED", "confirm_qty": "1"},
        {"event": "one_leg", "bet_key": leftover, "game": "LA Chargers vs Denver", "venue": "kalshi", "instrument": "KX-LACDEN", "confirm_qty": "1"},
    ]
    snap = _empty_ok_snap()
    snap["kalshi"] = [{"venue": "kalshi", "ticker": "KX-LACDEN", "qty": "1"}]
    snap["kalshi_by_ticker"] = {"KX-LACDEN": snap["kalshi"][0]}
    snap["kalshi_markets"] = {"KX-SETTLED": {"status": "closed"}}
    keys = live_lock_orders.open_lock_keys(
        rows,
        pid_alive=lambda pid: pid == 9,
        live_titles={"tampa bay vs carolina", "la chargers vs denver"},
        live_codes={("tbcar", "2026-10-25"), ("lacden", "2026-10-25")},
        watches=[{"bet_key": leftover, "filled_venue": "kalshi", "filled_instrument": "KX-LACDEN", "stopped": False}],
        poller_pids={"tampa bay vs carolina": 9},
        snapshot=snap,
    )
    assert claim not in keys
    assert empty not in keys
    assert flat not in keys
    assert settled not in keys
    assert leftover in keys
    assert keys == [leftover]


def test_filled_and_blocked():
    assert live_lock_orders.filled_contracts({"fill_count": "1.00", "remaining_count": "0.00"}) == Decimal("1.00")
    assert live_lock_orders.filled_contracts({"status": "cancelled"}) == Decimal("0")
    rows = [
        {"bet_key": "a", "event": "claim", "pid": 1},
        {"bet_key": "a", "event": "sent"},
        {"bet_key": "a", "event": "filled"},
        {"bet_key": "a", "event": "one_leg"},
    ]
    assert live_lock_orders.bet_blocked(rows, "a", lambda _pid: False)
    clear = [{"bet_key": "a", "event": "claim", "pid": 9}, {"bet_key": "a", "event": "sent"}, {"bet_key": "a", "event": "both_unfilled"}]
    assert not live_lock_orders.bet_blocked(clear, "a", lambda _pid: True)
    # Recheck skip is not a fill. The live tape writes event=skip, not preflight_skip.
    skipped = [{"bet_key": "a", "event": "claim", "pid": 9}, {"bet_key": "a", "event": "skip"}]
    assert not live_lock_orders.bet_blocked(skipped, "a", lambda _pid: True)
    filled_then_skip = [
        {"bet_key": "a", "event": "claim", "pid": 1},
        {"bet_key": "a", "event": "sent"},
        {"bet_key": "a", "event": "filled"},
        {"bet_key": "a", "event": "skip"},
    ]
    assert live_lock_orders.bet_blocked(filled_then_skip, "a", lambda _pid: False)


def test_one_leg_message_is_separate_from_the_under_1_ping():
    first = {"venue": "kalshi", "outcome": "yes", "instrument": "KX-TEST", "pay": "0.36"}
    second = {"venue": "gemini", "outcome": "no", "instrument": "GEMI-TEST", "pay": "0.34"}
    text = live_lock_orders.one_leg_message("Carolina vs Philadelphia", first, {"yes_price_dollars": "0.1100", "order_id": "abc"}, second, 201, "no message", {"order_id": "999"})
    assert text.startswith("one leg filled, other leg did not.")
    assert "Pair under $1" not in text
    assert "fill 0.1100" in text
    assert "Recovery did not fill" in text or "No further order was sent." in text


def test_one_leg_message_reads_gemini_avg_execution_price():
    first = {"venue": "gemini", "outcome": "yes", "instrument": "GEMI-NHL-2610190000-CAR-CGY-M-CGY", "pay": "0.42"}
    second = {"venue": "kalshi", "outcome": "no", "instrument": "KXNHLGAME-26OCT18CARCGY-CGY", "pay": "0.34"}
    payload = {"avgExecutionPrice": "0.99", "price": "0.4200", "filledQuantity": "1", "orderId": "145828837307202895"}
    text = live_lock_orders.one_leg_message("Carolina vs Calgary", first, payload, second, 201, "no message", None)
    assert "fill 0.99" in text
    assert "0.42" not in text
    assert live_lock_orders._execution_price(payload, "yes") == "0.99"


def test_send_returns_before_order_http_when_off():
    import tempfile
    from pathlib import Path

    saved_flag = live_lock_orders.ORDERS_ENABLED
    saved_stop = live_lock_orders.ORDERS_STOP
    saved_lock = live_lock_orders.lock_system_on
    live_lock_orders.ORDERS_ENABLED = False
    live_lock_orders.lock_system_on = lambda: True
    live_lock_orders.ORDERS_STOP = Path(tempfile.mkdtemp()) / "orders_stopped.json"
    calls = []

    def boom(*_args, **_kwargs):
        calls.append("http")
        raise AssertionError("order http was called")

    saved = (
        kalshi_private.signed_call,
        gemini_private.private_call,
        live_lock_orders.polymarket_us_live.signed_json,
    )
    kalshi_private.signed_call = boom
    gemini_private.private_call = boom
    live_lock_orders.polymarket_us_live.signed_json = boom
    try:
        for venue in ("kalshi", "gemini", "polymarket"):
            status, payload, note = live_lock_orders._send({"venue": venue, "body": {}})
            assert status == 0 and payload is None
            assert note == "placing orders is off"
        preview_ok, preview_note = live_lock_orders._preview({"venue": "polymarket", "body": {}})
        assert preview_ok is False
        assert preview_note == "placing orders is off"
    finally:
        kalshi_private.signed_call = saved[0]
        gemini_private.private_call = saved[1]
        live_lock_orders.polymarket_us_live.signed_json = saved[2]
        live_lock_orders.ORDERS_ENABLED = saved_flag
        live_lock_orders.ORDERS_STOP = saved_stop
        live_lock_orders.lock_system_on = saved_lock
    assert calls == []


def test_carolina_cap_allows_081_and_blocks_082():
    fill = Decimal("0.11")
    fee = live_lock_orders.kalshi_fee_amount(fill)
    assert fee == Decimal("0.0069")
    cap = live_lock_orders.max_gemini_price(fill, fee)
    assert cap == live_lock_orders.max_leg_price("gemini", fill, fee)
    assert cap is not None
    net = fill + fee + cap + live_lock_orders.gemini_taker_fee(cap)
    assert net <= live_lock_orders.effective_net_max()
    over = cap + Decimal("0.01")
    assert fill + fee + over + live_lock_orders.gemini_taker_fee(over) > live_lock_orders.effective_net_max()
    assert live_lock_orders.gemini_taker_fee(Decimal("0.81")) == Decimal("0.02")
    mid = live_lock_orders.midway_limit(Decimal("0.50"), cap, Decimal("0.01"))
    assert mid is not None and mid <= cap
    assert live_lock_orders.midway_limit(Decimal("0.90"), cap, Decimal("0.01")) is None
    assert not hasattr(live_lock_orders, "chase_gemini_limit")


def _gemini_spec():
    return {
        "venue": "gemini",
        "instrument": "GEMI-TEST",
        "outcome": "no",
        "pay": "0.34",
        "limit": "0.3400",
        "body": {},
        "intent": "",
        "fee_coefficient": None,
    }


def test_ioc_cancel_includes_the_gemini_email_case():
    cancelled = {"status": "cancelled", "filledQuantity": "0"}
    assert live_lock_orders.ioc_nothing_filled(201, cancelled)
    email = {
        "status": "canceled",
        "filledQuantity": "0",
        "reason": "Your limit buy because the order was submitted with the execution option Immediate Or Cancel but no part of the order would be filled immediately has been canceled.",
    }
    assert live_lock_orders.ioc_nothing_filled(201, email)
    assert not live_lock_orders.ioc_nothing_filled(201, {"status": "filled", "filledQuantity": "1"})


def test_websocket_read_times_out_when_the_price_never_arrives():
    state = {"t": 0}

    def clock():
        state["t"] += 1
        if state["t"] <= 2:
            return 0
        return 5

    price, why = live_lock_orders.read_websocket_price(
        _gemini_spec(), {}, timeout=2, clock=clock, sleep=lambda _seconds: None,
    )
    assert price is None and why == "timeout"


def test_leg_tries_websocket_then_book_then_midway_and_stops():
    sent = []

    def send(built):
        sent.append(built)
        if len(sent) < 3:
            return 201, {"status": "cancelled", "filledQuantity": "0", "reason": "ImmediateOrCancelWouldPost"}, "cancelled"
        return 201, {"status": "filled", "filledQuantity": "1"}, "filled"

    def read_ws(_spec, _books, timeout=2, clock=None, sleep=None):
        return Decimal("0.34"), "ok"

    def fetch_book(_spec):
        return Decimal("0.50"), "book"

    import tempfile
    from pathlib import Path

    saved_flag = live_lock_orders.ORDERS_ENABLED
    saved_stop = live_lock_orders.ORDERS_STOP
    saved_append = live_lock_orders._append
    saved_cash = _pin_balances("1000")
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = Path(tempfile.mkdtemp()) / "orders_stopped.json"
    live_lock_orders._append = lambda _row: None
    try:
        outcome = live_lock_orders.place_leg(
            lambda *_args, **_kwargs: None,
            "k",
            _gemini_spec(),
            {},
            Decimal("0.11"),
            Decimal("0.0069"),
            send=send,
            read_ws=read_ws,
            fetch_book=fetch_book,
        )
    finally:
        live_lock_orders.ORDERS_ENABLED = saved_flag
        live_lock_orders.ORDERS_STOP = saved_stop
        live_lock_orders._append = saved_append
        _unpin_balances(saved_cash)
    assert outcome["filled"] is True
    assert len(sent) == 3
    assert [row["body"]["timeInForce"] for row in sent] == ["immediate-or-cancel"] * 3
    assert [row["body"]["quantity"] for row in sent] == ["1"] * 3
    assert sent[0]["pay"] == "0.34"
    assert sent[1]["pay"] == "0.50"
    maximum = live_lock_orders.max_leg_price("gemini", Decimal("0.11"), Decimal("0.0069"))
    expected_mid = live_lock_orders.midway_limit(Decimal("0.50"), maximum, live_lock_orders.venue_tick("gemini"))
    assert sent[2]["pay"] == format(expected_mid, "f")


def test_timeout_uses_the_book_and_skips_a_midway_above_the_max():
    sent = []

    def send(built):
        sent.append(built)
        return 201, {"status": "cancelled", "filledQuantity": "0"}, "cancelled"

    def read_ws(_spec, _books, timeout=2, clock=None, sleep=None):
        return None, "timeout"

    def fetch_book(_spec):
        return Decimal("0.90"), "book"

    import tempfile
    from pathlib import Path

    saved_flag = live_lock_orders.ORDERS_ENABLED
    saved_stop = live_lock_orders.ORDERS_STOP
    saved_append = live_lock_orders._append
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = Path(tempfile.mkdtemp()) / "orders_stopped.json"
    live_lock_orders._append = lambda _row: None
    try:
        outcome = live_lock_orders.place_leg(
            lambda *_args, **_kwargs: None,
            "k",
            _gemini_spec(),
            {},
            Decimal("0.11"),
            Decimal("0.0069"),
            send=send,
            read_ws=read_ws,
            fetch_book=fetch_book,
        )
    finally:
        live_lock_orders.ORDERS_ENABLED = saved_flag
        live_lock_orders.ORDERS_STOP = saved_stop
        live_lock_orders._append = saved_append
    assert outcome["filled"] is False
    assert sent == []
    assert "limit=0.9" in outcome["note"]
    assert "cap gross under 1" in outcome["note"]
    assert "midway not sent" in outcome["note"]


def _arm_place(send, read_ws, fetch_book, spec, other_price, other_fee, cash="1000"):
    import tempfile
    from pathlib import Path

    saved_flag = live_lock_orders.ORDERS_ENABLED
    saved_stop = live_lock_orders.ORDERS_STOP
    saved_append = live_lock_orders._append
    saved_mid = live_lock_orders.midway_limit
    saved_cash = _pin_balances(cash)
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = Path(tempfile.mkdtemp()) / "orders_stopped.json"
    live_lock_orders._append = lambda _row: None
    lines = []
    try:
        outcome = live_lock_orders.place_leg(
            lambda message: lines.append(message),
            "k",
            spec,
            {},
            other_price,
            other_fee,
            send=send,
            read_ws=read_ws,
            fetch_book=fetch_book,
        )
    finally:
        live_lock_orders.ORDERS_ENABLED = saved_flag
        live_lock_orders.ORDERS_STOP = saved_stop
        live_lock_orders._append = saved_append
        live_lock_orders.midway_limit = saved_mid
        _unpin_balances(saved_cash)
    return outcome, lines


def test_calgary_book_ask_over_a_dollar_is_not_posted():
    sent = []

    def send(built):
        sent.append(built)
        return 201, {"status": "filled", "filledQuantity": "1", "avgExecutionPrice": "0.99"}, "filled"

    def read_ws(_spec, _books, timeout=2, clock=None, sleep=None):
        return None, "timeout"

    def fetch_book(_spec):
        return Decimal("0.99"), "book"

    outcome, lines = _arm_place(send, read_ws, fetch_book, _gemini_spec(), Decimal("0.34"), Decimal("0"))
    assert sent == []
    assert outcome["filled"] is False
    assert any("limit=0.99" in line and "other=0.34" in line and "not profitable" in line for line in lines)


def test_over_cap_quote_is_skipped_and_a_later_under_cap_try_is_sent():
    sent = []

    def send(built):
        sent.append(built)
        return 201, {"status": "filled", "filledQuantity": "1"}, "filled"

    def read_ws(_spec, _books, timeout=2, clock=None, sleep=None):
        return Decimal("0.99"), "ok"

    def fetch_book(_spec):
        return Decimal("0.40"), "book"

    outcome, _lines = _arm_place(send, read_ws, fetch_book, _gemini_spec(), Decimal("0.34"), Decimal("0"))
    assert outcome["filled"] is True
    assert [row["pay"] for row in sent] == ["0.40"]


def test_over_cap_book_can_still_send_a_midway_price_under_the_cap():
    sent = []

    def send(built):
        sent.append(built)
        return 201, {"status": "filled", "filledQuantity": "1"}, "filled"

    def read_ws(_spec, _books, timeout=2, clock=None, sleep=None):
        return None, "timeout"

    def fetch_book(_spec):
        return Decimal("0.99"), "book"

    saved_mid = live_lock_orders.midway_limit
    live_lock_orders.midway_limit = lambda _quoted, _maximum, _tick: Decimal("0.50")
    try:
        outcome, lines = _arm_place(send, read_ws, fetch_book, _gemini_spec(), Decimal("0.34"), Decimal("0"))
    finally:
        live_lock_orders.midway_limit = saved_mid
    assert outcome["filled"] is True
    assert [row["pay"] for row in sent] == ["0.50"]
    assert any("book" in line and "limit=0.99" in line for line in lines)


def test_kalshi_leg_is_not_sent_when_the_gemini_fill_is_no_longer_profitable():
    sent = []
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "no",
        "pay": "0.34",
        "limit": "0.6600",
        "body": {},
        "intent": "",
        "fee_coefficient": None,
    }

    def send(built):
        sent.append(built)
        return 201, {"status": "filled", "filledQuantity": "1"}, "filled"

    def read_ws(_spec, _books, timeout=2, clock=None, sleep=None):
        return Decimal("0.34"), "ok"

    def fetch_book(_spec):
        return Decimal("0.34"), "book"

    outcome, lines = _arm_place(send, read_ws, fetch_book, spec, Decimal("0.99"), Decimal("0.01"))
    assert sent == []
    assert outcome["filled"] is False
    assert any("not profitable" in line and "other=0.99" in line for line in lines)


def test_simultaneous_legs_and_only_a_one_leg_latches():
    import tempfile
    from pathlib import Path
    import novig_live

    folder = Path(tempfile.mkdtemp())
    saved_novig_live = novig_live.orders_live
    novig_live.orders_live = lambda: False
    flag = folder / "orders_stopped.json"
    watch_path = folder / "one_leg_watch.json"
    saved = (
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.place_leg,
        live_lock_orders._one_ioc,
        live_lock_orders._append,
        live_lock_orders.alert_one_leg,
        live_lock_orders._phone_trade_result,
        live_lock_orders.refresh_balances,
        live_lock_orders._phone_orders_off,
        live_lock_orders._refresh_order_pages,
        live_lock_orders._spec_at_price,
        live_lock_orders._funds_block,
        live_lock_orders._profit_block,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders.WATCH_LOCK,
        live_lock_orders.fetch_book_ask,
        live_lock_orders._phone_watch_note,
        live_lock_orders._log_consider,
    )
    ioc_calls = []
    recovery_calls = []
    flatten_calls = []
    phones = []
    off_pings = []
    kalshi = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "instrument": "KX", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.40"}
    gemini = {"venue": "gemini", "outcome": "no", "pay": "0.50", "instrument": "G", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.50"}
    poly = {"venue": "polymarket", "outcome": "yes", "pay": "0.40", "instrument": "slug", "intent": "ORDER_INTENT_BUY_LONG", "fee_coefficient": None, "body": {}, "limit": "0.40"}

    def fake_spec(spec, pay):
        built = dict(spec)
        built["pay"] = format(pay, "f") if hasattr(pay, "quantize") else str(pay)
        built["limit"] = built["pay"]
        built["body"] = built.get("body") or {"price": built["pay"]}
        return built

    def miss_ioc(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
        ioc_calls.append(spec["venue"])
        return {"filled": False, "payload": None, "status": 201, "note": "cancelled", "pay": spec.get("pay"), "spec": spec, "step": step, "posted": True}

    def quiet_ioc(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
        ioc_calls.append(spec["venue"])
        return {"filled": False, "payload": None, "status": 0, "note": "not posted", "pay": spec.get("pay"), "spec": spec, "step": step, "posted": False}

    live_lock_orders.ORDERS_STOP = flag
    live_lock_orders.ONE_LEG_WATCH = watch_path
    live_lock_orders.WATCH_LOCK = folder / "one_leg_watch.lock"
    saved_last_skip = live_lock_orders.LAST_SKIP
    live_lock_orders.LAST_SKIP = folder / "lock_last_skip.json"
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders._spec_at_price = fake_spec
    live_lock_orders._funds_block = lambda _built: ""
    live_lock_orders._profit_block = lambda *_a, **_k: ""
    live_lock_orders._phone_watch_note = lambda *_a, **_k: None

    def fake_book(spec, **_k):
        live_lock_orders._attach_quote_size(spec, "10")
        pay = live_lock_orders._dec(spec.get("pay")) or Decimal("0.40")
        return pay, "book"

    live_lock_orders.fetch_book_ask = fake_book
    live_lock_orders._one_ioc = miss_ioc
    live_lock_orders.place_leg = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("recovery not expected"))
    live_lock_orders._append = lambda _row: None
    live_lock_orders._log_consider = lambda *_a, **_k: None
    live_lock_orders.alert_one_leg = lambda *_args, **_kwargs: None
    live_lock_orders._phone_trade_result = lambda _log, message, success: phones.append((success, message))
    live_lock_orders._phone_orders_off = lambda filled, missed: off_pings.append((filled, missed))
    refreshed = []
    live_lock_orders.refresh_balances = lambda log=None: refreshed.append(1)
    live_lock_orders._refresh_order_pages = lambda: None
    try:
        live_lock_orders._send_pair(lambda *_args, **_kwargs: None, "k", "Game", [kalshi, gemini])
        assert ioc_calls == ["gemini"]
        assert refreshed == []
        assert not flag.exists()
        assert live_lock_orders.ORDERS_ENABLED is True
        assert len(phones) == 1
        assert phones[0][0] is False
        assert "hard miss abort" in phones[0][1]
        assert off_pings == []

        ioc_calls.clear()
        phones.clear()
        live_lock_orders._one_ioc = quiet_ioc
        live_lock_orders._send_pair(lambda *_args, **_kwargs: None, "k", "Game", [kalshi, gemini])
        assert ioc_calls == ["gemini"]
        assert phones == []
        assert off_pings == []
        assert not flag.exists()

        ioc_calls.clear()

        def one_ioc(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
            ioc_calls.append(spec["venue"])
            if step == "flatten":
                flatten_calls.append(spec["venue"])
                return {
                    "filled": False,
                    "payload": {"status": "cancelled", "filledQuantity": "0"},
                    "status": 201,
                    "note": "flatten miss",
                    "pay": spec.get("pay"),
                    "spec": spec,
                    "step": step,
                    "posted": True,
                }
            filled = spec["venue"] == "gemini"
            return {
                "filled": filled,
                "payload": {"status": "filled" if filled else "cancelled", "filledQuantity": "1" if filled else "0"},
                "status": 201,
                "note": "filled" if filled else "cancelled",
                "pay": spec.get("pay"),
                "spec": spec,
                "step": step,
                "posted": True,
            }

        def recovery_miss(_log, _key, spec, _books, _other_price, _other_fee, **_kwargs):
            recovery_calls.append(spec["venue"])
            return {
                "filled": False,
                "payload": {"status": "cancelled", "filledQuantity": "0"},
                "status": 201,
                "note": "cancelled",
                "pay": spec.get("pay"),
                "spec": spec,
                "step": "recovery",
                "posted": True,
            }

        live_lock_orders._one_ioc = one_ioc
        live_lock_orders.place_leg = recovery_miss
        live_lock_orders._send_pair(lambda *_args, **_kwargs: None, "k", "Game", [kalshi, gemini])
        assert "gemini" in ioc_calls and "kalshi" in ioc_calls
        assert flatten_calls == ["gemini"]
        assert recovery_calls == []
        assert refreshed == [1]
        assert flag.is_file()
        stored = json.loads(flag.read_text(encoding="utf-8"))
        assert stored["reason"] == "one leg filled and the other missed"
        assert phones and phones[-1][0] is False
        assert len(off_pings) == 1
        assert off_pings[0][0]["venue"] == "gemini"
        assert off_pings[0][1]["venue"] == "kalshi"
        assert watch_path.is_file()
        stored_watch = json.loads(watch_path.read_text(encoding="utf-8"))
        assert stored_watch["filled_venue"] == "gemini"
        assert stored_watch["missed_venue"] == "kalshi"
        assert stored_watch["fill_px"]
        assert stored_watch["max_other_price"]
        live_lock_orders.stop_orders("one leg filled and the other missed", {"venue": "gemini"}, {"venue": "kalshi"})
        assert len(off_pings) == 1
        live_lock_orders.ORDERS_ENABLED = True
        assert live_lock_orders.orders_halted() is True
        assert live_lock_orders.ORDERS_ENABLED is False
        flag.unlink()
        if watch_path.exists():
            watch_path.unlink()
        ioc_calls.clear()
        recovery_calls.clear()
        phones.clear()

        def both_ioc(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
            ioc_calls.append(spec["venue"])
            return {"filled": True, "payload": {"status": "filled", "filledQuantity": "1"}, "status": 201, "note": "filled", "pay": spec.get("pay"), "spec": spec, "step": step, "posted": True}

        live_lock_orders._one_ioc = both_ioc
        live_lock_orders.place_leg = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no recovery"))
        live_lock_orders.ORDERS_ENABLED = True
        live_lock_orders._send_pair(lambda *_args, **_kwargs: None, "k", "Game", [poly, gemini])
        assert sorted(ioc_calls) == ["gemini", "polymarket"]
        assert refreshed == [1, 1]
        assert not flag.exists()
        assert live_lock_orders.ORDERS_ENABLED is True
        assert phones and phones[-1][0] is True
        assert len(off_pings) == 1

        ioc_calls.clear()
        phones.clear()
        off_pings.clear()
        lines = []
        live_lock_orders._send_pair(lambda message: lines.append(str(message)), "k", "Game", [kalshi, poly])
        assert sorted(ioc_calls) == ["kalshi", "polymarket"]
        assert not any("not Gemini" in line or "Polymarket first" in line for line in lines)
        assert not flag.exists()

        ioc_calls.clear()
        novig = {"venue": "novig", "outcome": "no", "pay": "0.40", "instrument": "N", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.40"}
        live_lock_orders._send_pair(lambda message: lines.append(str(message)), "k", "Game", [kalshi, novig])
        assert ioc_calls == []
        assert any("novig" in line and ("not two" in line or "two distinct" in line or "not sent" in line) for line in lines)

        ioc_calls.clear()
        phones.clear()
        off_pings.clear()
        recovery_calls.clear()

        def qty_ioc(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
            ioc_calls.append(spec["venue"])
            if step == "flatten":
                flatten_calls.append(spec["venue"])
                return {
                    "filled": False,
                    "payload": {"status": "cancelled", "filledQuantity": "0"},
                    "status": 201,
                    "note": "flatten miss",
                    "pay": spec.get("pay"),
                    "spec": spec,
                    "step": step,
                    "posted": True,
                }
            qty = "1" if spec["venue"] == "polymarket" else "0"
            return {
                "filled": False,
                "payload": {"status": "cancelled", "filledQuantity": qty},
                "status": 201,
                "note": "cancelled",
                "pay": spec.get("pay"),
                "spec": spec,
                "step": step,
                "posted": True,
            }

        def fake_book_poly_thin(spec, **_k):
            venue = str(spec.get("venue") or "")
            live_lock_orders._attach_quote_size(spec, "1" if venue == "polymarket" else "10")
            pay = live_lock_orders._dec(spec.get("pay")) or Decimal("0.40")
            return pay, "book"

        live_lock_orders.fetch_book_ask = fake_book_poly_thin
        live_lock_orders._one_ioc = qty_ioc
        live_lock_orders.place_leg = recovery_miss
        saved_leg_fee = live_lock_orders.leg_fee
        live_lock_orders.leg_fee = lambda spec, price, payload=None: Decimal("0")
        flatten_calls.clear()
        try:
            live_lock_orders._send_pair(lambda *_args, **_kwargs: None, "k", "Game", [poly, gemini])
        finally:
            live_lock_orders.leg_fee = saved_leg_fee
        assert "gemini" in ioc_calls and "polymarket" in ioc_calls
        assert flatten_calls == ["polymarket"]
        assert recovery_calls == []
        assert flag.is_file()
        assert off_pings[-1][0]["venue"] == "polymarket"
        assert off_pings[-1][1]["venue"] == "gemini"
        flag.unlink()
        if watch_path.exists():
            watch_path.unlink()
        live_lock_orders.ORDERS_ENABLED = True

        ioc_calls.clear()
        off_pings.clear()

        def fractional_ioc(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
            ioc_calls.append(spec["venue"])
            return {
                "filled": False,
                "payload": {"status": "cancelled", "filledQuantity": "0.4"},
                "status": 201,
                "note": "cancelled",
                "pay": spec.get("pay"),
                "spec": spec,
                "step": step,
                "posted": True,
            }

        live_lock_orders.fetch_book_ask = fake_book
        live_lock_orders._one_ioc = fractional_ioc
        live_lock_orders.place_leg = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no recovery"))
        live_lock_orders._send_pair(lambda *_args, **_kwargs: None, "k", "Game", [kalshi, gemini])
        assert ioc_calls == ["gemini"]
        assert not flag.exists()
        assert off_pings == []
    finally:
        live_lock_orders.ORDERS_ENABLED = saved[0]
        live_lock_orders.ORDERS_STOP = saved[1]
        live_lock_orders.place_leg = saved[2]
        live_lock_orders._one_ioc = saved[3]
        live_lock_orders._append = saved[4]
        live_lock_orders.alert_one_leg = saved[5]
        live_lock_orders._phone_trade_result = saved[6]
        live_lock_orders.refresh_balances = saved[7]
        live_lock_orders._phone_orders_off = saved[8]
        live_lock_orders._refresh_order_pages = saved[9]
        live_lock_orders._spec_at_price = saved[10]
        live_lock_orders._funds_block = saved[11]
        live_lock_orders._profit_block = saved[12]
        live_lock_orders.ONE_LEG_WATCH = saved[13]
        live_lock_orders.WATCH_LOCK = saved[14]
        live_lock_orders.fetch_book_ask = saved[15]
        live_lock_orders._phone_watch_note = saved[16]
        live_lock_orders._log_consider = saved[17]
        live_lock_orders.LAST_SKIP = saved_last_skip
        live_lock_orders._clear_consider()
        novig_live.orders_live = saved_novig_live
        if flag.exists():
            flag.unlink()
        if watch_path.exists():
            watch_path.unlink()


def test_one_sided_fill_stops_for_any_venue():
    filled = {"filled": True, "payload": {"status": "filled", "filledQuantity": "1"}}
    missed = {"filled": False, "payload": {"status": "cancelled", "filledQuantity": "0"}}
    assert live_lock_orders.exactly_one_leg_filled(filled, missed)
    assert live_lock_orders.exactly_one_leg_filled(missed, filled)
    assert not live_lock_orders.exactly_one_leg_filled(missed, missed)
    assert not live_lock_orders.exactly_one_leg_filled(filled, filled)
    assert not live_lock_orders.exactly_one_leg_filled(missed, None)
    assert not live_lock_orders.exactly_one_leg_filled(None, None)


def test_short_or_unread_balance_is_not_sent():
    assert live_lock_orders.contract_cost({"venue": "kalshi", "fee_coefficient": None}, "0.40") == Decimal("0.4168")
    fee = live_lock_orders.gemini_taker_fee(Decimal("0.34"))
    assert live_lock_orders.contract_cost({"venue": "gemini", "fee_coefficient": None}, Decimal("0.34")) == Decimal("0.34") + fee

    sent = []

    def send(built):
        sent.append(built)
        return 201, {"status": "filled", "filledQuantity": "1"}, "filled"

    def read_ws(_spec, _books, timeout=2, clock=None, sleep=None):
        return Decimal("0.34"), "ok"

    def fetch_book(_spec):
        return Decimal("0.20"), "book"

    seen_low = []
    saved_consider_low = live_lock_orders._log_consider
    live_lock_orders._log_consider = lambda decision, reason, *a, **k: seen_low.append(reason)
    try:
        outcome, lines = _arm_place(send, read_ws, fetch_book, _gemini_spec(), Decimal("0.11"), Decimal("0.0069"), cash="0.01")
        assert any(reason.startswith("Gemini balance too low") and "$0.01" in reason and "need $" in reason for reason in seen_low)
    finally:
        live_lock_orders._log_consider = saved_consider_low
    assert sent == []
    assert outcome["filled"] is False
    assert any("venue=gemini" in line and "cost=" in line and "balance=0.01" in line for line in lines)

    import tempfile
    from pathlib import Path

    saved_fetch = live_lock_orders._fetch_venue_balance
    live_lock_orders._fetch_venue_balance = lambda _venue: None
    seen = []
    saved_consider = live_lock_orders._log_consider
    saved_unread = live_lock_orders._UNREAD_ALERT
    saved_phone = live_lock_orders._phone_watch_note
    live_lock_orders._log_consider = lambda decision, reason, *a, **k: seen.append(reason)
    live_lock_orders._UNREAD_ALERT = Path(tempfile.mkdtemp()) / "kalshi_unread_alert.json"
    live_lock_orders._phone_watch_note = lambda *_a, **_k: None
    try:
        outcome, lines = _arm_place(send, read_ws, fetch_book, _gemini_spec(), Decimal("0.11"), Decimal("0.0069"), cash=None)
        # Fail-soft: skip send only. Do not flood the opportunities log.
        assert not any(reason == "Gemini balance unreadable" for reason in seen)
    finally:
        live_lock_orders._fetch_venue_balance = saved_fetch
        live_lock_orders._log_consider = saved_consider
        live_lock_orders._UNREAD_ALERT = saved_unread
        live_lock_orders._phone_watch_note = saved_phone
    assert sent == []
    assert any("venue=gemini" in line and "cost=" in line and "balance=unread" in line for line in lines)


def test_balance_deny_reason_names_venue_and_low_vs_unread():
    assert live_lock_orders._balance_deny_reason("novig", None, Decimal("0.43")) == "Novig balance unreadable"
    assert live_lock_orders._balance_deny_reason("novig", Decimal("0"), Decimal("0.43")) == "Novig balance too low ($0 need $0.43)"
    assert live_lock_orders._balance_deny_reason("kalshi", None, None) == "Kalshi balance unreadable"
    assert live_lock_orders._balance_deny_reason("gemini", Decimal("0.01"), Decimal("0.35")) == "Gemini balance too low ($0.01 need $0.35)"
    assert live_lock_orders._balance_deny_reason("polymarket", Decimal("1"), Decimal("2")) == "Polymarket balance too low ($1 need $2)"
    assert live_lock_orders._balance_deny_from_funds("venue=novig cost=0.43 balance=0") == "Novig balance too low ($0 need $0.43)"
    assert live_lock_orders._balance_deny_from_funds("venue=kalshi cost=0.40 balance=unread") == "Kalshi balance unreadable"
    assert live_lock_orders._balance_deny_from_probe("novig balance http 500", "novig") == "Novig balance unreadable"
    assert live_lock_orders._balance_deny_from_probe("balance does not cover 1 contract", "novig") == "Novig balance too low"


def test_kalshi_probe_429_uses_last_good():
    """A 429 GET must not mark Kalshi incapable when last-good cash is on disk."""
    saved_usd = kalshi_private.balance_usd
    saved_cap = dict(live_lock_orders._capability)
    saved_bal = dict(live_lock_orders._venue_balances)
    saved_seeded = live_lock_orders._balances_seeded
    saved_live = dict(live_lock_orders._venue_balance_live_at)
    live_lock_orders._capability.clear()
    live_lock_orders._balances_seeded = True
    live_lock_orders._venue_balances.clear()
    live_lock_orders._venue_balances["kalshi"] = Decimal("21.35")
    live_lock_orders._venue_balance_live_at["kalshi"] = 1.0
    kalshi_private.balance_usd = lambda: (429, None)
    try:
        ok, reason = live_lock_orders._probe("kalshi")
        assert ok is True
        assert "last-good" in reason
        ok2, _why = live_lock_orders._capability_ok("kalshi", 1_000_000.0)
        assert ok2 is True
    finally:
        kalshi_private.balance_usd = saved_usd
        live_lock_orders._capability.clear()
        live_lock_orders._capability.update(saved_cap)
        live_lock_orders._venue_balances.clear()
        live_lock_orders._venue_balances.update(saved_bal)
        live_lock_orders._balances_seeded = saved_seeded
        live_lock_orders._venue_balance_live_at.clear()
        live_lock_orders._venue_balance_live_at.update(saved_live)


def test_unread_skip_rate_limit_does_not_append_every_tick():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = (
        live_lock_orders.ORDERS,
        live_lock_orders.LAST_SKIP,
        live_lock_orders._UNREAD_ALERT,
        live_lock_orders._refresh_order_pages,
        live_lock_orders._phone_watch_note,
    )
    live_lock_orders.ORDERS = folder / "orders.jsonl"
    live_lock_orders.LAST_SKIP = folder / "lock_last_skip.json"
    live_lock_orders._UNREAD_ALERT = folder / "kalshi_unread_alert.json"
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders._phone_watch_note = lambda *_a, **_k: None
    try:
        assert live_lock_orders._record_unread_balance_skip(
            "Kalshi balance unreadable", "Miami vs New York J", "a"
        )
        assert not live_lock_orders._record_unread_balance_skip(
            "Kalshi balance unreadable", "San Francisco vs Atlanta", "b"
        )
        text = live_lock_orders.ORDERS.read_text(encoding="utf-8")
        assert text.count("Kalshi balance unreadable") == 1
    finally:
        live_lock_orders.ORDERS = saved[0]
        live_lock_orders.LAST_SKIP = saved[1]
        live_lock_orders._UNREAD_ALERT = saved[2]
        live_lock_orders._refresh_order_pages = saved[3]
        live_lock_orders._phone_watch_note = saved[4]


def test_stale_zero_balance_is_refetched():
    import tempfile
    from datetime import datetime
    from pathlib import Path
    from zoneinfo import ZoneInfo

    tmp = Path(tempfile.mkdtemp()) / "balances.json"
    import venue_cash_local

    saved = (
        live_lock_orders.BALANCES_FILE,
        dict(live_lock_orders._venue_balances),
        live_lock_orders._balances_seeded,
        live_lock_orders._balances_at,
        dict(live_lock_orders._venue_balance_live_at),
        live_lock_orders._fetch_venue_balance,
        venue_cash_local.CASH_FILE,
    )
    live_lock_orders.BALANCES_FILE = tmp
    venue_cash_local.reset_for_tests(Path(tempfile.mkdtemp()) / "venue_cash_local.json")
    live_lock_orders._balances_seeded = True
    live_lock_orders._balances_at = datetime.max.replace(tzinfo=ZoneInfo("America/New_York"))
    live_lock_orders._venue_balances.clear()
    live_lock_orders._venue_balance_live_at.clear()
    live_lock_orders._venue_balances["novig"] = Decimal("0")
    live_lock_orders._fetch_venue_balance = lambda venue: Decimal("10") if venue == "novig" else None
    try:
        cash = live_lock_orders.ensure_venue_balance("novig")
        assert cash == Decimal("10")
        spec = {"venue": "kalshi", "limit": "0.40", "pay": "0.40", "fee_coefficient": None}
        live_lock_orders._venue_balances["kalshi"] = Decimal("0")
        live_lock_orders._venue_balance_live_at.pop("kalshi", None)
        live_lock_orders._fetch_venue_balance = lambda venue: Decimal("21.44") if venue == "kalshi" else None
        assert live_lock_orders._funds_block(spec) == ""
        assert live_lock_orders._venue_balances["kalshi"] == Decimal("21.44")
    finally:
        live_lock_orders.BALANCES_FILE = saved[0]
        live_lock_orders._venue_balances.clear()
        live_lock_orders._venue_balances.update(saved[1])
        live_lock_orders._balances_seeded = saved[2]
        live_lock_orders._balances_at = saved[3]
        live_lock_orders._venue_balance_live_at.clear()
        live_lock_orders._venue_balance_live_at.update(saved[4])
        live_lock_orders._fetch_venue_balance = saved[5]
        venue_cash_local.CASH_FILE = saved[6]


def test_failed_balance_read_keeps_last_good():
    import tempfile
    from datetime import datetime
    from pathlib import Path
    import time
    from zoneinfo import ZoneInfo

    tmp = Path(tempfile.mkdtemp()) / "balances.json"
    import venue_cash_local

    saved = (
        live_lock_orders.BALANCES_FILE,
        dict(live_lock_orders._venue_balances),
        live_lock_orders._balances_seeded,
        live_lock_orders._balances_at,
        dict(live_lock_orders._venue_balance_live_at),
        live_lock_orders._fetch_venue_balance,
        venue_cash_local.CASH_FILE,
    )
    live_lock_orders.BALANCES_FILE = tmp
    venue_cash_local.reset_for_tests(Path(tempfile.mkdtemp()) / "venue_cash_local.json")
    live_lock_orders._balances_seeded = True
    live_lock_orders._balances_at = datetime.max.replace(tzinfo=ZoneInfo("America/New_York"))
    live_lock_orders._venue_balances.clear()
    live_lock_orders._venue_balance_live_at.clear()
    live_lock_orders._venue_balances["kalshi"] = Decimal("21.44")
    live_lock_orders._venue_balance_live_at["kalshi"] = time.time() - 120
    live_lock_orders._fetch_venue_balance = lambda _venue: None
    try:
        assert live_lock_orders.ensure_venue_balance("kalshi") == Decimal("21.44")
        spec = {"venue": "kalshi", "limit": "0.40", "pay": "0.40", "fee_coefficient": None}
        assert live_lock_orders._funds_block(spec) == ""
        live_lock_orders._venue_balances["kalshi"] = Decimal("0")
        live_lock_orders._venue_balance_live_at["kalshi"] = time.time()
        live_lock_orders._fetch_venue_balance = lambda _venue: Decimal("0")
        note = live_lock_orders._funds_block(spec)
        assert note.startswith("venue=kalshi")
        assert "balance=0" in note
    finally:
        live_lock_orders.BALANCES_FILE = saved[0]
        live_lock_orders._venue_balances.clear()
        live_lock_orders._venue_balances.update(saved[1])
        live_lock_orders._balances_seeded = saved[2]
        live_lock_orders._balances_at = saved[3]
        live_lock_orders._venue_balance_live_at.clear()
        live_lock_orders._venue_balance_live_at.update(saved[4])
        live_lock_orders._fetch_venue_balance = saved[5]
        venue_cash_local.CASH_FILE = saved[6]


def test_gemini_book_ask_reads_the_websocket_fields():
    events = [{
        "contracts": [{
            "instrumentSymbol": "GEMI-TEST",
            "prices": {"buy": {"yes": "0.40", "no": "0.62"}, "bestAsk": "0.40"},
        }]
    }]
    assert live_lock_orders.gemini_book_ask(events, "GEMI-TEST", "yes") == Decimal("0.40")
    assert live_lock_orders.gemini_book_ask(events, "GEMI-TEST", "no") == Decimal("0.62")
    assert live_lock_orders.gemini_book_ask(events, "OTHER", "yes") is None


def test_order_io_redacts_secret_keys_and_keeps_reason():
    body = json.dumps({"status": "cancelled", "filledQuantity": "0", "reason": "ImmediateOrCancelWouldPost", "signature": "should-not-store"})
    stored = live_lock_orders._response_for_store(body)
    assert stored["reason"] == "ImmediateOrCancelWouldPost"
    assert stored["filledQuantity"] == "0"
    assert stored["signature"] == "[redacted]"
    request = live_lock_orders._redact_obj({"symbol": "GEMI-TEST", "apiKey": "hidden"})
    assert request["apiKey"] == "[redacted]"
    assert request["symbol"] == "GEMI-TEST"


def test_gemini_order_fields_match_the_rest_shape():
    body = live_lock_orders.gemini_order_payload("GEMI-NFL-2610181700-CAR-PHI-T-O40", "no", Decimal("0.34"))
    assert body == {
        "symbol": "GEMI-NFL-2610181700-CAR-PHI-T-O40",
        "orderType": "limit",
        "side": "buy",
        "quantity": "1",
        "price": "0.3400",
        "outcome": "no",
        "timeInForce": "immediate-or-cancel",
    }


def test_poly_order_body_is_fok_kalshi_gemini_novig_still_ioc():
    import novig_live

    body = live_lock_orders.polymarket_order_body(
        "aec-utr-guaale-bralac-2026-10-24", "ORDER_INTENT_BUY_LONG", Decimal("0.48")
    )
    assert body["tif"] == "TIME_IN_FORCE_FILL_OR_KILL"
    assert body["tif"] == live_lock_orders.POLY_TIF_FOK
    assert body["quantity"] == 1
    assert body["type"] == "ORDER_TYPE_LIMIT"
    kalshi = live_lock_orders.kalshi_order_body("KX-TEST", "yes", Decimal("0.40"), "cid")
    assert kalshi["time_in_force"] == "immediate_or_cancel"
    gemini = live_lock_orders.gemini_order_payload("GEMI-TEST", "yes", Decimal("0.40"))
    assert gemini["timeInForce"] == "immediate-or-cancel"
    novig = novig_live.order_body("oid", Decimal("0.40"), "cid")
    assert novig["tif"] == "IOC"


def test_poly_size_019_skip_does_not_post():
    import tempfile
    from pathlib import Path

    posted = []
    folder = Path(tempfile.mkdtemp())

    def boom(*_a, **_k):
        posted.append(1)
        raise AssertionError("polymarket POST")

    def fetch(spec, **_k):
        live_lock_orders._attach_quote_size(spec, "0.19", overwrite=True)
        return Decimal("0.48"), "book"

    saved = (
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.polymarket_us_live.signed_json,
        live_lock_orders.fetch_book_ask,
        live_lock_orders.record_send_skip,
    )
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders.polymarket_us_live.signed_json = boom
    live_lock_orders.fetch_book_ask = fetch
    live_lock_orders.record_send_skip = lambda *_a, **_k: None
    body = live_lock_orders.polymarket_order_body(
        "aec-utr-guaale-bralac-2026-10-24", "ORDER_INTENT_BUY_LONG", Decimal("0.48")
    )
    spec = {
        "venue": "polymarket",
        "instrument": "aec-utr-guaale-bralac-2026-10-24",
        "outcome": "yes",
        "intent": "ORDER_INTENT_BUY_LONG",
        "body": body,
        "_strategy_b": True,
        "quote_source": "book",
        "quote_size": "0.19",
    }
    try:
        status, payload, note = live_lock_orders._send(spec)
    finally:
        live_lock_orders.ORDERS_ENABLED = saved[0]
        live_lock_orders.ORDERS_STOP = saved[1]
        live_lock_orders.polymarket_us_live.signed_json = saved[2]
        live_lock_orders.fetch_book_ask = saved[3]
        live_lock_orders.record_send_skip = saved[4]
    assert posted == []
    assert status == 0
    assert payload is None
    assert live_lock_orders.POLY_SIZE_LT_QTY_SKIP in note
    assert live_lock_orders.poly_size_lt_qty_skip(spec, rest=False)


def test_poly_size_ge_1_fok_fill_1_is_house_open():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    posted = []
    fill = json.dumps({
        "id": "oid-fok-1",
        "cumQuantity": 1,
        "leavesQuantity": 0,
        "state": "ORDER_STATE_FILLED",
        "avgPx": {"value": "0.4800"},
    })

    def fake_signed(method, path, body):
        posted.append((method, path, body.get("tif"), body.get("quantity")))
        return 200, fill

    def fetch(spec, **_k):
        live_lock_orders._attach_quote_size(spec, "2", overwrite=True)
        return Decimal("0.48"), "book"

    saved = (
        live_lock_orders.ORDERS,
        live_lock_orders.ORDER_IO,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        live_lock_orders._with_venue_confirm,
        live_lock_orders._register_send_fill_watch,
        live_lock_orders.fetch_book_ask,
        live_lock_orders.polymarket_us_live.signed_json,
        live_lock_orders.record_send_skip,
    )
    live_lock_orders.ORDERS = folder / "orders.jsonl"
    live_lock_orders.ORDER_IO = folder / "order_io.jsonl"
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders._phone_order_placed = lambda _spec: None
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders._register_send_fill_watch = lambda *_a, **_k: None
    live_lock_orders.fetch_book_ask = fetch
    live_lock_orders.polymarket_us_live.signed_json = fake_signed
    live_lock_orders.record_send_skip = lambda *_a, **_k: None
    live_lock_orders._with_venue_confirm = lambda spec, status, payload: venue_fill_confirm.attach(
        payload or {},
        {"known": True, "qty": "1", "house_fill": True, "note": "fok fill 1"},
    )
    body = live_lock_orders.polymarket_order_body(
        "aec-test", "ORDER_INTENT_BUY_LONG", Decimal("0.48")
    )
    spec = {
        "venue": "polymarket",
        "instrument": "aec-test",
        "outcome": "yes",
        "intent": "ORDER_INTENT_BUY_LONG",
        "body": body,
        "_strategy_b": True,
        "quote_source": "book",
        "quote_size": "2",
        "_bet_key": "k",
        "_step": "t0",
        "_attempt": 1,
    }
    try:
        status, payload, _note = live_lock_orders._send(spec)
    finally:
        live_lock_orders.ORDERS = saved[0]
        live_lock_orders.ORDER_IO = saved[1]
        live_lock_orders.ORDERS_ENABLED = saved[2]
        live_lock_orders.ORDERS_STOP = saved[3]
        live_lock_orders.ONE_LEG_WATCH = saved[4]
        live_lock_orders._phone_order_placed = saved[5]
        live_lock_orders._refresh_order_pages = saved[6]
        live_lock_orders._with_venue_confirm = saved[7]
        live_lock_orders._register_send_fill_watch = saved[8]
        live_lock_orders.fetch_book_ask = saved[9]
        live_lock_orders.polymarket_us_live.signed_json = saved[10]
        live_lock_orders.record_send_skip = saved[11]
    assert posted == [("POST", "/v1/orders", "TIME_IN_FORCE_FILL_OR_KILL", 1)]
    assert status == 200
    assert live_lock_orders.filled_contracts(payload) >= Decimal("1")
    house = venue_fill_confirm._known_result(
        "polymarket", Decimal("1"), Decimal("0.48"), "fok", 200, Decimal("1"),
        {"order_id": "oid-fok-1"}, house_size=Decimal("1"),
    )
    assert house["house_fill"] is True


def test_guajardo_002_book_skips_poly():
    import tempfile
    from pathlib import Path

    import novig_live

    folder = Path(tempfile.mkdtemp())
    sent = []

    def fetch_ask(spec, **_k):
        if str(spec.get("venue") or "") == "polymarket":
            live_lock_orders._attach_quote_size(spec, "0.02", overwrite=True)
            return Decimal("0.48"), "book"
        return None, "missing"

    def fake_send(spec):
        sent.append(spec["venue"])
        return 200, {"id": "should-not", "cumQuantity": 1}, "filled"

    watch = {
        "bet_key": "tennis\tguajarbrain\t2026-10-24\tmoneyline\tcode:GUA\t\tpolymarket\tkalshi",
        "game": "Alexander Guajardo vs. Lachlan Brain",
        "sport": "tennis",
        "market_type": "moneyline",
        "claim_side": "Guajardo",
        "started_at": "2026-10-24T12:00:00-04:00",
        "filled_venue": "kalshi",
        "filled_instrument": "KX-BRAIN",
        "filled_side": "yes",
        "fill_px": "0.40",
        "fill_fee": "0.01",
        "origin_venue": "kalshi",
        "missed_venue": "polymarket",
        "missed_instrument": "aec-utr-guaale-bralac-2026-10-24",
        "missed_side": "yes",
        "missed_intent": "ORDER_INTENT_BUY_LONG",
        "max_other_price": "0.60",
        "watch_mode": "continuous_quote",
        "stopped": False,
        "venues": {
            "polymarket": {
                "instrument": "aec-utr-guaale-bralac-2026-10-24",
                "intent": "ORDER_INTENT_BUY_LONG",
                "fee_coefficient": "0.0695",
            },
            "kalshi": {"instrument": "KX-BRAIN"},
        },
    }
    spec = {
        "venue": "polymarket",
        "instrument": "aec-utr-guaale-bralac-2026-10-24",
        "intent": "ORDER_INTENT_BUY_LONG",
        "body": live_lock_orders.polymarket_order_body(
            "aec-utr-guaale-bralac-2026-10-24", "ORDER_INTENT_BUY_LONG", Decimal("0.48")
        ),
        "quote_size": "0.02",
        "quote_source": "book",
    }
    live_lock_orders._attach_quote_size(spec, "0.02", overwrite=True)
    assert live_lock_orders.POLY_SIZE_LT_QTY_SKIP in live_lock_orders.poly_size_lt_qty_skip(spec, rest=False)

    saved_novig = novig_live.NOVIG_ORDERS_ENABLED
    novig_live.NOVIG_ORDERS_ENABLED = False
    saved, flag, watch_path = _watch_harness(folder, watch, fetch_ask, fake_send)
    saved_pin = _pin_balances("1000")
    try:
        status = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert sent == []
        assert status in {live_lock_orders.POLY_SIZE_LT_QTY_SKIP, "no qualifying"}
        assert live_lock_orders.watch_is_active()
        assert status != "deadline"
    finally:
        novig_live.NOVIG_ORDERS_ENABLED = saved_novig
        _unpin_balances(saved_pin)
        _restore_watch_harness(saved)


def _shard_404():
    payload = {
        "error": {
            "code": "insufficient_shard_balance",
            "message": "insufficient shard balance",
            "details": "Exchange user not found.",
        }
    }
    return 404, payload, "insufficient_shard_balance Exchange user not found."


def test_shard_user_404_retries_the_same_limit_twice_more():
    import tempfile
    from pathlib import Path

    sent = []
    sleeps = []
    rows = []

    def send(built):
        sent.append((built["pay"], built["limit"], built["body"], built.get("_attempt")))
        return _shard_404()

    saved_flag = live_lock_orders.ORDERS_ENABLED
    saved_stop = live_lock_orders.ORDERS_STOP
    saved_append = live_lock_orders._append
    saved_sleep = live_lock_orders.time.sleep
    saved_cash = _pin_balances("1000")
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = Path(tempfile.mkdtemp()) / "orders_stopped.json"
    live_lock_orders._append = rows.append
    live_lock_orders.time.sleep = lambda seconds: sleeps.append(seconds)
    spec = {
        "venue": "kalshi",
        "instrument": "KXATPMATCH-26OCT18FARBAL-BAL",
        "outcome": "no",
        "pay": "0.38",
        "intent": "",
        "fee_coefficient": None,
    }
    try:
        outcome = live_lock_orders._one_ioc(
            lambda *_args, **_kwargs: None, "k", spec, Decimal("0.38"), "websocket", send, Decimal("0.54"), Decimal("0.02")
        )
    finally:
        live_lock_orders.ORDERS_ENABLED = saved_flag
        live_lock_orders.ORDERS_STOP = saved_stop
        live_lock_orders._append = saved_append
        live_lock_orders.time.sleep = saved_sleep
        _unpin_balances(saved_cash)
    assert outcome["filled"] is False
    assert outcome["status"] == 404
    assert outcome["advance"] is False
    assert len(sent) == 3
    assert sleeps == [2, 2]
    assert [row[3] for row in sent] == [1, 2, 3]
    assert len({row[0] for row in sent}) == 1
    assert len({json.dumps(row[2], sort_keys=True) for row in sent}) == 1
    assert sent[0][2]["count"] == "1.00"
    assert [row["attempt"] for row in rows] == [1, 2, 3]


def test_shard_user_404_stops_when_a_later_post_is_accepted():
    import tempfile
    from pathlib import Path

    sent = []

    def send(built):
        sent.append(built.get("_attempt"))
        if len(sent) == 1:
            return _shard_404()
        return 201, {"status": "filled", "fill_count": "1.00", "order_id": "abc"}, "filled"

    saved_flag = live_lock_orders.ORDERS_ENABLED
    saved_stop = live_lock_orders.ORDERS_STOP
    saved_append = live_lock_orders._append
    saved_sleep = live_lock_orders.time.sleep
    saved_cash = _pin_balances("1000")
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = Path(tempfile.mkdtemp()) / "orders_stopped.json"
    live_lock_orders._append = lambda _row: None
    live_lock_orders.time.sleep = lambda _seconds: None
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "yes",
        "pay": "0.40",
        "intent": "",
        "fee_coefficient": None,
    }
    try:
        outcome = live_lock_orders._one_ioc(
            lambda *_args, **_kwargs: None, "k", spec, Decimal("0.40"), "websocket", send, Decimal("0.40"), Decimal("0")
        )
    finally:
        live_lock_orders.ORDERS_ENABLED = saved_flag
        live_lock_orders.ORDERS_STOP = saved_stop
        live_lock_orders._append = saved_append
        live_lock_orders.time.sleep = saved_sleep
        _unpin_balances(saved_cash)
    assert sent == [1, 2]
    assert outcome["filled"] is True


def test_ordinary_reject_and_ioc_cancel_are_not_retried():
    import tempfile
    from pathlib import Path

    sent = []

    def send(built):
        sent.append(built.get("_attempt"))
        if len(sent) == 1:
            return 400, {"error": {"code": "insufficient_balance", "message": "insufficient balance"}}, "insufficient balance"
        return 201, {"status": "cancelled", "fill_count": "0.00", "remaining_count": "0.00"}, "cancelled"

    saved_flag = live_lock_orders.ORDERS_ENABLED
    saved_stop = live_lock_orders.ORDERS_STOP
    saved_append = live_lock_orders._append
    saved_sleep = live_lock_orders.time.sleep
    saved_cash = _pin_balances("1000")
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = Path(tempfile.mkdtemp()) / "orders_stopped.json"
    live_lock_orders._append = lambda _row: None
    live_lock_orders.time.sleep = lambda _seconds: (_ for _ in ()).throw(AssertionError("slept"))
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "yes",
        "pay": "0.40",
        "intent": "",
        "fee_coefficient": None,
    }
    try:
        first = live_lock_orders._one_ioc(
            lambda *_args, **_kwargs: None, "k", spec, Decimal("0.40"), "websocket", send, Decimal("0.40"), Decimal("0")
        )
        second = live_lock_orders._one_ioc(
            lambda *_args, **_kwargs: None, "k2", spec, Decimal("0.40"), "book", send, Decimal("0.40"), Decimal("0")
        )
    finally:
        live_lock_orders.ORDERS_ENABLED = saved_flag
        live_lock_orders.ORDERS_STOP = saved_stop
        live_lock_orders._append = saved_append
        live_lock_orders.time.sleep = saved_sleep
        _unpin_balances(saved_cash)
    assert sent == [1, 1]
    assert first["status"] == 400 and first["filled"] is False
    assert second["status"] == 201 and second["filled"] is False and second["advance"] is True


def test_one_ioc_keeps_partial_fill_qty_after_cancel():
    import tempfile
    from pathlib import Path

    cancelled = []

    def send(_built):
        return 201, {
            "status": "open",
            "filledQuantity": "0.62",
            "remainingQuantity": "0.38",
        }, "open"

    saved_flag = live_lock_orders.ORDERS_ENABLED
    saved_stop = live_lock_orders.ORDERS_STOP
    saved_append = live_lock_orders._append
    saved_cancel = live_lock_orders._cancel
    saved_cash = _pin_balances("1000")
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = Path(tempfile.mkdtemp()) / "orders_stopped.json"
    live_lock_orders._append = lambda _row: None
    live_lock_orders._cancel = lambda *_a, **_k: cancelled.append(1) or (200, "cancelled")
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "yes",
        "pay": "0.40",
        "intent": "",
        "fee_coefficient": None,
    }
    try:
        outcome = live_lock_orders._one_ioc(
            lambda *_args, **_kwargs: None, "k", spec, Decimal("0.40"), "book", send, Decimal("0.40"), Decimal("0")
        )
    finally:
        live_lock_orders.ORDERS_ENABLED = saved_flag
        live_lock_orders.ORDERS_STOP = saved_stop
        live_lock_orders._append = saved_append
        live_lock_orders._cancel = saved_cancel
        _unpin_balances(saved_cash)
    assert cancelled == [1]
    assert outcome["filled"] is False
    assert outcome["advance"] is False
    assert live_lock_orders.outcome_fill_qty(outcome) == Decimal("0.62")
    assert Decimal(str(outcome["fill_qty"])) == Decimal("0.62")


def test_shard_user_posts_are_each_logged_in_order_io():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = (
        live_lock_orders.ORDER_IO,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders._phone_order_placed,
        kalshi_private.signed_call,
        live_lock_orders._refresh_order_pages,
    )
    live_lock_orders.ORDER_IO = folder / "order_io.jsonl"
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders._phone_order_placed = lambda _spec: None
    live_lock_orders._refresh_order_pages = lambda: None
    body = json.dumps({
        "error": {
            "code": "insufficient_shard_balance",
            "message": "insufficient shard balance",
            "details": "Exchange user not found.",
        }
    })
    kalshi_private.signed_call = lambda *_args, **_kwargs: (404, body)
    spec = {"venue": "kalshi", "instrument": "KX-TEST", "outcome": "no", "limit": "0.6200", "body": {"ticker": "KX-TEST", "count": "1.00", "price": "0.6200"}, "_attempt": 2}
    try:
        status, _payload, note = live_lock_orders._send(spec)
    finally:
        live_lock_orders.ORDER_IO = saved[0]
        live_lock_orders.ORDERS_ENABLED = saved[1]
        live_lock_orders.ORDERS_STOP = saved[2]
        live_lock_orders._phone_order_placed = saved[3]
        kalshi_private.signed_call = saved[4]
        live_lock_orders._refresh_order_pages = saved[5]
    assert status == 404
    assert "insufficient_shard_balance" in note
    line = json.loads((folder / "order_io.jsonl").read_text(encoding="utf-8").strip())
    assert line["http_status"] == 404
    assert line["attempt"] == 2
    assert line["kind"] == "order"
    assert "insufficient_shard_balance" in json.dumps(line["response"])


def test_send_schedules_performance_on_confirmed_fill_not_on_deny():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    scheduled = []
    saved = (
        live_lock_orders.ORDERS,
        live_lock_orders.ORDER_IO,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        live_lock_orders._with_venue_confirm,
        live_lock_orders._register_send_fill_watch,
        kalshi_private.signed_call,
        orders_performance_refresh.schedule_rebuild,
    )
    live_lock_orders.ORDERS = folder / "orders.jsonl"
    live_lock_orders.ORDER_IO = folder / "order_io.jsonl"
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders._phone_order_placed = lambda _spec: None
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders._register_send_fill_watch = lambda *_a, **_k: None
    orders_performance_refresh.schedule_rebuild = lambda reason: scheduled.append(reason) or True

    def confirm_fill(spec, status, payload):
        qty = "1.00" if status in (200, 201) else "0"
        return venue_fill_confirm.attach(payload or {}, {"known": True, "qty": qty, "note": "test"})

    live_lock_orders._with_venue_confirm = confirm_fill
    fill_body = json.dumps({"average_fill_price": "0.3400", "fill_count": "1.00", "order_id": "oid-fill"})
    deny_body = json.dumps({"error": {"code": "insufficient_shard_balance", "message": "insufficient shard balance"}})
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "no",
        "limit": "0.6200",
        "body": {"ticker": "KX-TEST"},
        "_attempt": 1,
        "_bet_key": "game",
        "_step": "websocket",
    }
    try:
        kalshi_private.signed_call = lambda *_a, **_k: (201, fill_body)
        status, payload, _note = live_lock_orders._send(spec)
        assert status == 201
        assert live_lock_orders.filled_contracts(payload) >= Decimal("1")
        assert scheduled == ["fill"]
        scheduled.clear()
        kalshi_private.signed_call = lambda *_a, **_k: (404, deny_body)
        status, _payload, note = live_lock_orders._send(spec)
        assert status == 404
        assert "insufficient_shard_balance" in note
        assert scheduled == []
        kalshi_private.signed_call = lambda *_a, **_k: (201, json.dumps({"fill_count": "0.00", "status": "executed"}))

        def confirm_empty(spec, status, payload):
            return venue_fill_confirm.attach(payload or {}, {"known": True, "qty": "0", "note": "empty 201"})

        live_lock_orders._with_venue_confirm = confirm_empty
        status, payload, _note = live_lock_orders._send(spec)
        assert status == 201
        assert live_lock_orders.filled_contracts(payload) == Decimal("0")
        assert scheduled == []
    finally:
        live_lock_orders.ORDERS = saved[0]
        live_lock_orders.ORDER_IO = saved[1]
        live_lock_orders.ORDERS_ENABLED = saved[2]
        live_lock_orders.ORDERS_STOP = saved[3]
        live_lock_orders.ONE_LEG_WATCH = saved[4]
        live_lock_orders._phone_order_placed = saved[5]
        live_lock_orders._refresh_order_pages = saved[6]
        live_lock_orders._with_venue_confirm = saved[7]
        live_lock_orders._register_send_fill_watch = saved[8]
        kalshi_private.signed_call = saved[9]
        orders_performance_refresh.schedule_rebuild = saved[10]


def test_send_rebuilds_pages_on_request_and_on_result():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    pages = []
    saved = (
        live_lock_orders.ORDERS,
        live_lock_orders.ORDER_IO,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        kalshi_private.signed_call,
    )
    live_lock_orders.ORDERS = folder / "orders.jsonl"
    live_lock_orders.ORDER_IO = folder / "order_io.jsonl"
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders._phone_order_placed = lambda _spec: None
    live_lock_orders._refresh_order_pages = lambda: pages.append("both")
    body = json.dumps({"error": {"code": "insufficient_shard_balance", "message": "insufficient shard balance"}})
    kalshi_private.signed_call = lambda *_args, **_kwargs: (404, body)
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "no",
        "limit": "0.6200",
        "body": {"ticker": "KX-TEST"},
        "_attempt": 1,
        "_bet_key": "game",
        "_step": "websocket",
    }
    try:
        status, _payload, note = live_lock_orders._send(spec)
    finally:
        live_lock_orders.ORDERS = saved[0]
        live_lock_orders.ORDER_IO = saved[1]
        live_lock_orders.ORDERS_ENABLED = saved[2]
        live_lock_orders.ORDERS_STOP = saved[3]
        live_lock_orders._phone_order_placed = saved[4]
        live_lock_orders._refresh_order_pages = saved[5]
        kalshi_private.signed_call = saved[6]
    assert status == 404
    assert "insufficient_shard_balance" in note
    assert pages == ["both", "both"]
    rows = [json.loads(line) for line in (folder / "orders.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["event"] == "sent"
    assert rows[0]["http_status"] == 404
    assert rows[0]["note"] != "request sent"


def test_send_returns_kalshi_fill_when_ledger_replace_fails():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = (
        live_lock_orders.ORDERS,
        live_lock_orders.ORDER_IO,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        live_lock_orders._complete_order_post,
        kalshi_private.signed_call,
    )

    def boom(*_args, **_kwargs):
        raise PermissionError("Access is denied")

    live_lock_orders.ORDERS = folder / "orders.jsonl"
    live_lock_orders.ORDER_IO = folder / "order_io.jsonl"
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders._phone_order_placed = lambda _spec: None
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders._complete_order_post = boom
    order_body = json.dumps({
        "average_fill_price": "0.3400",
        "fill_count": "1.00",
        "order_id": "oid-landaluce",
        "remaining_count": "0.00",
    })
    fills = json.dumps({
        "fills": [{
            "order_id": "oid-landaluce",
            "ticker": "KXATPMATCH-26OCT18WAWLAN-LAN",
            "count_fp": "1.00",
            "yes_price_dollars": "0.6600",
            "no_price_dollars": "0.3400",
            "outcome_side": "no",
        }],
        "cursor": "",
    })

    def fake_signed(method, path, body=None, query=None, timeout=30):
        if "portfolio/fills" in str(path):
            return 200, fills
        return 201, order_body

    kalshi_private.signed_call = fake_signed
    spec = {
        "venue": "kalshi",
        "instrument": "KXATPMATCH-26OCT18WAWLAN-LAN",
        "outcome": "no",
        "limit": "0.3100",
        "body": {"ticker": "KXATPMATCH-26OCT18WAWLAN-LAN", "side": "ask"},
        "_attempt": 1,
        "_bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:LAN\t\tpolymarket\tkalshi",
        "_step": "simultaneous",
    }
    try:
        status, payload, _note = live_lock_orders._send(spec)
    finally:
        live_lock_orders.ORDERS = saved[0]
        live_lock_orders.ORDER_IO = saved[1]
        live_lock_orders.ORDERS_ENABLED = saved[2]
        live_lock_orders.ORDERS_STOP = saved[3]
        live_lock_orders.ONE_LEG_WATCH = saved[4]
        live_lock_orders._phone_order_placed = saved[5]
        live_lock_orders._refresh_order_pages = saved[6]
        live_lock_orders._complete_order_post = saved[7]
        kalshi_private.signed_call = saved[8]
    assert status == 201
    assert live_lock_orders.filled_contracts(payload) == Decimal("1.00")
    assert live_lock_orders.leg_filled_at_least_one({
        "payload": payload, "filled": False, "status": 201,
    })


def test_pending_kalshi_row_uses_order_io_fill_count():
    import tempfile
    from pathlib import Path
    import order_ledger

    folder = Path(tempfile.mkdtemp())
    saved = order_ledger.ORDERS, order_ledger.ORDER_IO, order_ledger.SUPERVISOR_LOG
    orders = folder / "orders.jsonl"
    io_path = folder / "order_io.jsonl"
    orders.write_text(
        json.dumps({
            "event": "claim",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:LAN\t\tpolymarket\tkalshi",
            "game": "Wawrinka vs Landaluce",
            "market_type": "moneyline",
            "side": "Martin Landaluce",
            "compared_at": "2026-10-21T08:59:52.613-04:00",
        }) + "\n" + json.dumps({
            "event": "sent",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:LAN\t\tpolymarket\tkalshi",
            "venue": "kalshi",
            "instrument": "KXATPMATCH-26OCT18WAWLAN-LAN",
            "side": "no",
            "limit_price": "0.3100",
            "http_status": "pending",
            "note": "request sent",
            "order_id": "",
            "attempt": 1,
        }) + "\n" + json.dumps({
            "event": "sent",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:LAN\t\tpolymarket\tkalshi",
            "venue": "polymarket",
            "instrument": "aec-atp-stawaw-marlan-2026-10-18",
            "side": "no",
            "limit_price": "0.750",
            "http_status": 200,
            "note": "no message",
            "order_id": "D7XH7B9010JB",
            "attempt": 1,
        }) + "\n",
        encoding="utf-8",
    )
    io_path.write_text(
        json.dumps({
            "timestamp": "2026-10-21T08:59:52-04:00",
            "venue": "kalshi",
            "kind": "order",
            "request": {"ticker": "KXATPMATCH-26OCT18WAWLAN-LAN", "side": "ask", "price": "0.3100"},
            "http_status": 201,
            "response": {
                "average_fee_paid": "0.0158",
                "average_fill_price": "0.3400",
                "fill_count": "1.00",
                "order_id": "01a15e8b-ed58-7562-84a7-9115332799fa",
                "remaining_count": "0.00",
            },
        }) + "\n" + json.dumps({
            "timestamp": "2026-10-21T08:59:53-04:00",
            "venue": "polymarket",
            "kind": "order",
            "request": {"marketSlug": "aec-atp-stawaw-marlan-2026-10-18", "intent": "ORDER_INTENT_BUY_SHORT"},
            "http_status": 200,
            "response": {"id": "D7XH7B9010JB", "executions": [{"lastShares": "0.0000", "order": {"state": "ORDER_STATE_EXPIRED", "cumQuantity": 0}}]},
        }) + "\n",
        encoding="utf-8",
    )
    order_ledger.ORDERS = orders
    order_ledger.ORDER_IO = io_path
    order_ledger.SUPERVISOR_LOG = folder / "missing.log"
    try:
        rows = order_ledger._new_sent_rows([])
    finally:
        order_ledger.ORDERS, order_ledger.ORDER_IO, order_ledger.SUPERVISOR_LOG = saved
    assert rows
    kalshi = next(cells for cells in rows if cells[order_ledger.COL["Venue"]] == "kalshi")
    assert kalshi[order_ledger.COL["Filled"]] == "yes"
    assert kalshi[order_ledger.COL["Outcome"]] == "one leg"
    assert kalshi[order_ledger.COL["HTTP"]] == "201"
    assert kalshi[order_ledger.COL["System"]] == "A Lock gap"


def test_result_replaces_pending_order_row():
    import order_ledger

    def row(http: str, order_id: str, outcome: str, when: str = "") -> list[str]:
        cells = [""] * order_ledger.COL_COUNT
        cells[0] = "1"
        cells[order_ledger.COL["System"]] = "A Lock gap"
        cells[order_ledger.COL["Venue"]] = "kalshi"
        cells[order_ledger.COL["Instrument"]] = "KX-TEST"
        cells[order_ledger.COL["Limit price"]] = "0.6200"
        cells[order_ledger.COL["HTTP"]] = http
        cells[order_ledger.COL["Outcome"]] = outcome
        cells[order_ledger.COL["Time"]] = when
        cells[order_ledger.COL["Order id"]] = order_id
        return cells

    pending = row("pending", "", "neither filled")
    result = row("404", "", "one leg", "2026-10-19T11:00")
    merged = order_ledger._apply_fresh_rows([pending], [result])
    assert len(merged) == 1
    assert merged[0][order_ledger.COL["HTTP"]] == "404"
    assert merged[0][order_ledger.COL["Outcome"]] == "one leg"
    assert merged[0][0] == "1"
    again = order_ledger._apply_fresh_rows(merged, [result])
    assert len(again) == 1


def test_spot_order_path_is_refused():
    try:
        gemini_private.private_call("/v1/order/new", {"symbol": "btcusd"}, "POST")
    except ValueError:
        return
    raise AssertionError("spot order path should be refused")


def test_pick_trigger_uses_the_newest_nonzero_move():
    quotes = [
        {"venue": "kalshi", "side": "yes", "price": "0.5900", "seen_at": "2026-10-20T07:37:57.000000-04:00", "source": "websocket"},
        {"venue": "polymarket", "side": "no", "price": "0.3400", "seen_at": "2026-10-20T07:37:57.491377-04:00", "source": "websocket"},
    ]
    fresh = [
        {"venue": "Kalshi", "pay": "yes", "price": "0.5900", "seen_at": "2026-10-20T07:37:50.000000-04:00", "move": "0.0000"},
        {"venue": "Polymarket", "pay": "no", "price": "0.3400", "seen_at": "2026-10-20T07:37:57.491377-04:00", "move": "-0.0400"},
    ]
    trigger = live_lock_orders._pick_trigger(quotes, fresh)
    assert trigger["venue"] == "polymarket"
    assert trigger["side"] == "no"
    assert trigger["price"] == "0.3400"
    assert "07:37:57" in trigger["seen_at"]
    assert live_lock_orders.quote_source_for_step("simultaneous") == "websocket"
    assert live_lock_orders.quote_source_for_step("hard") == "book"
    assert live_lock_orders.quote_source_for_step("easy") == "book"
    assert live_lock_orders.quote_source_for_step("book") == "book"
    assert live_lock_orders.quote_source_for_step("midway") == "recovery-cap"


def test_sent_row_and_order_io_keep_trigger_quotes():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = (
        live_lock_orders.ORDER_IO,
        live_lock_orders.ORDERS,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        kalshi_private.signed_call,
    )
    live_lock_orders.ORDER_IO = folder / "order_io.jsonl"
    live_lock_orders.ORDERS = folder / "orders.jsonl"
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders._phone_order_placed = lambda _spec: None
    live_lock_orders._refresh_order_pages = lambda: None
    kalshi_private.signed_call = lambda *_args, **_kwargs: (201, json.dumps({"order_id": "oid-1", "fill_count": "0.00"}))
    spec = {
        "venue": "kalshi",
        "instrument": "KXATPCHALLENGERMATCH-26OCT20NAGSAN-NAG",
        "outcome": "yes",
        "pay": "0.5900",
        "limit": "0.5900",
        "body": {"ticker": "KXATPCHALLENGERMATCH-26OCT20NAGSAN-NAG", "price": "0.5900", "side": "bid"},
        "_attempt": 1,
        "_bet_key": "nagsan",
        "_step": "simultaneous",
        "quote_source": "websocket",
        "quote_price": "0.5900",
        "quote_seen_at": "2026-10-20T07:37:57.187886-04:00",
        "trigger_venue": "polymarket",
        "trigger_side": "no",
        "trigger_price": "0.3400",
        "trigger_seen_at": "2026-10-20T07:37:57.491377-04:00",
        "trigger_source": "websocket",
    }
    try:
        status, _payload, _note = live_lock_orders._send(spec)
    finally:
        live_lock_orders.ORDER_IO = saved[0]
        live_lock_orders.ORDERS = saved[1]
        live_lock_orders.ORDERS_ENABLED = saved[2]
        live_lock_orders.ORDERS_STOP = saved[3]
        live_lock_orders._phone_order_placed = saved[4]
        live_lock_orders._refresh_order_pages = saved[5]
        kalshi_private.signed_call = saved[6]
    assert status == 201
    sent = json.loads((folder / "orders.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
    assert sent["quote_source"] == "websocket"
    assert sent["quote_price"] == "0.5900"
    assert sent["quote_seen_at"].startswith("2026-10-20T07:37:57")
    assert sent["trigger_venue"] == "polymarket"
    assert sent["trigger_price"] == "0.3400"
    assert sent["sent_at"]
    assert sent["lag_seconds"] != ""
    io_row = json.loads((folder / "order_io.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
    assert io_row["quote"]["quote_source"] == "websocket"
    assert io_row["quote"]["trigger_price"] == "0.3400"
    assert "signature" not in json.dumps(io_row).lower()
    assert io_row["request"]["ticker"] == "KXATPCHALLENGERMATCH-26OCT20NAGSAN-NAG"
    assert "quote" not in io_row["request"]


def test_watch_ioc_sends_while_latch_on_and_fill_turns_orders_back_on():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    flag = folder / "orders_stopped.json"
    watch_path = folder / "one_leg_watch.json"
    saved = (
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders.WATCH_LOCK,
        live_lock_orders._send,
        live_lock_orders.fetch_book_ask,
        live_lock_orders.missed_market_closed,
        live_lock_orders._watch_ws_live,
        live_lock_orders._phone_watch_note,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        live_lock_orders.refresh_balances,
        live_lock_orders._append,
        live_lock_orders._read_orders,
        live_lock_orders._halt_logged,
    )
    live_lock_orders.ORDERS_STOP = flag
    live_lock_orders.ONE_LEG_WATCH = watch_path
    live_lock_orders.WATCH_LOCK = folder / "watch.lock"
    live_lock_orders._phone_watch_note = lambda *_a, **_k: None
    live_lock_orders._phone_order_placed = lambda *_a, **_k: None
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders.refresh_balances = lambda log=None: None
    live_lock_orders._append = lambda _row: None
    live_lock_orders._read_orders = lambda: []
    live_lock_orders.missed_market_closed = lambda _spec: (False, "open")
    live_lock_orders._watch_ws_live = lambda *_a, **_k: False

    def ask_for(spec, **_k):
        venue = str(spec.get("venue") or "")
        if venue == "gemini":
            return Decimal("0.40"), "book"
        if venue == "kalshi":
            return Decimal("0.70"), "book"
        return None, "missing"

    live_lock_orders.fetch_book_ask = ask_for
    sent = []

    def fake_send(spec):
        sent.append(dict(spec))
        assert spec.get("_watch_recovery") is True
        return 201, {"status": "filled", "filledQuantity": "1"}, "filled"

    live_lock_orders._send = fake_send
    flag.write_text(json.dumps({"stopped": True, "reason": "one leg filled and the other missed"}), encoding="utf-8")
    live_lock_orders.ORDERS_ENABLED = False
    live_lock_orders._halt_logged = True
    watch = {
        "bet_key": "k",
        "game": "Middle Tennessee vs FIU",
        "sport": "college football",
        "market_type": "total",
        "claim_side": "over",
        "number": "48.5",
        "started_at": "2026-10-20T19:32:10-04:00",
        "filled_venue": "kalshi",
        "filled_instrument": "KXNCAAFTOTAL-26OCT20MTUFIU-49",
        "filled_side": "no",
        "fill_px": "0.3300",
        "fill_fee": "0",
        "missed_venue": "gemini",
        "missed_instrument": "GEMI-NCAAF-2610202300-MTN-FIU-T-O48",
        "missed_side": "yes",
        "missed_intent": "",
        "max_other_price": "0.60",
        "stopped": False,
    }
    watch_path.write_text(json.dumps(watch), encoding="utf-8")
    saved_pin = _pin_balances("1000")
    try:
        status = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert status == "filled"
        assert sent and sent[0]["venue"] == "gemini"
        assert Decimal(sent[0]["pay"]) == Decimal("0.40")
        assert not flag.exists()
        assert not watch_path.exists()
        assert live_lock_orders.ORDERS_ENABLED is True
        live_lock_orders.ORDERS_ENABLED = False
        flag.write_text("{}", encoding="utf-8")
        watch["fill_px"] = "0.3300"
        watch["max_other_price"] = "0.50"
        watch_path.write_text(json.dumps(watch), encoding="utf-8")
        live_lock_orders.fetch_book_ask = lambda _spec, **_k: (Decimal("0.73"), "book")
        sent.clear()
        status = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert status == "no qualifying"
        assert sent == []
        assert flag.exists()
        assert live_lock_orders.watch_is_active()
    finally:
        _unpin_balances(saved_pin)
        live_lock_orders.ORDERS_ENABLED = saved[0]
        live_lock_orders.ORDERS_STOP = saved[1]
        live_lock_orders.ONE_LEG_WATCH = saved[2]
        live_lock_orders.WATCH_LOCK = saved[3]
        live_lock_orders._send = saved[4]
        live_lock_orders.fetch_book_ask = saved[5]
        live_lock_orders.missed_market_closed = saved[6]
        live_lock_orders._watch_ws_live = saved[7]
        live_lock_orders._phone_watch_note = saved[8]
        live_lock_orders._phone_order_placed = saved[9]
        live_lock_orders._refresh_order_pages = saved[10]
        live_lock_orders.refresh_balances = saved[11]
        live_lock_orders._append = saved[12]
        live_lock_orders._read_orders = saved[13]
        live_lock_orders._halt_logged = saved[14]


def test_leftover_watch_loop_has_no_datetime_cutoff():
    import inspect

    assert not hasattr(live_lock_orders, "WATCH_DEADLINE")
    src = inspect.getsource(live_lock_orders._tick_single_watch)
    assert "WATCH_DEADLINE" not in src
    assert "REQUIRED_DEADLINE" not in src
    assert "8:00 AM ET deadline" not in src
    assert "now >=" not in src
    locked = inspect.getsource(live_lock_orders._tick_one_leg_watch_locked)
    assert "WATCH_DEADLINE" not in locked
    loop = inspect.getsource(live_lock_orders.ensure_watch_ticker)
    assert "WATCH_DEADLINE" not in loop
    assert "deadline" not in loop.lower()


def test_leftover_after_friday_8am_still_eligible():
    import tempfile
    from datetime import datetime
    from pathlib import Path

    import novig_live

    folder = Path(tempfile.mkdtemp())
    sent = []
    frozen = datetime(2026, 10, 22, 8, 1, 0, tzinfo=live_lock_orders.ET)
    real_dt = live_lock_orders.datetime

    class FrozenDateTime(real_dt):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen

    def fetch_ask(spec, **_k):
        venue = str(spec.get("venue") or "")
        if venue == "gemini":
            return Decimal("0.40"), "book"
        return None, "missing"

    def fake_send(spec):
        sent.append(spec["venue"])
        return 201, {"status": "filled", "filledQuantity": "1"}, "filled"

    saved_novig = novig_live.NOVIG_ORDERS_ENABLED
    novig_live.NOVIG_ORDERS_ENABLED = False
    saved, flag, watch_path = _watch_harness(folder, _mtu_watch(), fetch_ask, fake_send)
    saved_pin = _pin_balances("1000")
    live_lock_orders.datetime = FrozenDateTime
    try:
        status = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert status != "deadline"
        assert status == "filled"
        assert sent == ["gemini"]
        assert not live_lock_orders.watch_is_active()
        assert not flag.exists()
        assert not watch_path.exists()
    finally:
        live_lock_orders.datetime = real_dt
        novig_live.NOVIG_ORDERS_ENABLED = saved_novig
        _unpin_balances(saved_pin)
        _restore_watch_harness(saved)


def test_watch_tick_errors_do_not_raise():
    import tempfile
    from pathlib import Path

    saved = (live_lock_orders.load_all_watches, live_lock_orders.WATCH_LOCK)
    live_lock_orders.WATCH_LOCK = Path(tempfile.mkdtemp()) / "watch.lock"
    live_lock_orders.load_all_watches = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        status = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert status == "error"
    finally:
        live_lock_orders.load_all_watches = saved[0]
        live_lock_orders.WATCH_LOCK = saved[1]


def test_reconstruct_watch_from_mtu_one_leg():
    saved_net = live_lock_orders.NET_MAX
    live_lock_orders.NET_MAX = Decimal("0.95")
    rows = [
        {
            "event": "claim",
            "bet_key": "college football\tmtufiu\t2026-10-20\ttotal\tover\t48.5\tgemini\tkalshi",
            "sport": "college football",
            "game": "Middle Tennessee vs FIU",
            "market_type": "total",
            "side": "over",
            "number": "48.5",
        },
        {
            "event": "sent",
            "bet_key": "college football\tmtufiu\t2026-10-20\ttotal\tover\t48.5\tgemini\tkalshi",
            "venue": "gemini",
            "instrument": "GEMI-NCAAF-2610202300-MTN-FIU-T-O48",
            "side": "yes",
            "limit_price": "0.5800",
        },
        {
            "event": "sent",
            "bet_key": "college football\tmtufiu\t2026-10-20\ttotal\tover\t48.5\tgemini\tkalshi",
            "venue": "kalshi",
            "instrument": "KXNCAAFTOTAL-26OCT20MTUFIU-49",
            "side": "no",
            "limit_price": "0.6700",
        },
        {
            "event": "filled",
            "bet_key": "college football\tmtufiu\t2026-10-20\ttotal\tover\t48.5\tgemini\tkalshi",
            "venue": "kalshi",
            "instrument": "KXNCAAFTOTAL-26OCT20MTUFIU-49",
            "side": "no",
            "price": "0.3300",
        },
        {
            "event": "one_leg",
            "bet_key": "college football\tmtufiu\t2026-10-20\ttotal\tover\t48.5\tgemini\tkalshi",
            "venue": "kalshi",
            "instrument": "KXNCAAFTOTAL-26OCT20MTUFIU-49",
            "side": "no",
            "price": "0.3300",
            "second_venue": "gemini",
        },
    ]
    try:
        watch, note = live_lock_orders.reconstruct_watch_from_orders(rows)
        assert note == "ok", note
        assert watch["game"] == "Middle Tennessee vs FIU"
        assert watch["filled_venue"] == "kalshi"
        assert watch["fill_px"] == "0.3300"
        assert watch["missed_venue"] == "gemini"
        assert watch["missed_side"] == "yes"
        assert watch["origin_venue"] == "kalshi"
        assert watch["opposite_side"] == "yes"
        assert watch["watch_mode"] == "continuous_quote"
        fill = Decimal("0.3300")
        fill_fee = live_lock_orders.kalshi_fee_amount(fill)
        assert Decimal(watch["fill_fee"]) == fill_fee
        assert Decimal(watch["max_other_price"]) == live_lock_orders.max_leg_price("gemini", fill, fill_fee)
        # BUY_SHORT avgPx matching the sent house limit is cash paid, not a Yes-wire to invert.
        cash = live_lock_orders._polymarket_fill_cash("no", Decimal("0.3600"), Decimal("0.360"))
        assert cash == Decimal("0.3600")
        yes_wire = live_lock_orders._polymarket_fill_cash("no", Decimal("0.6400"), Decimal("0.360"))
        assert yes_wire == Decimal("0.360")
    finally:
        live_lock_orders.NET_MAX = saved_net


def _watch_harness(folder, watch, fetch_ask, send):
    flag = folder / "orders_stopped.json"
    watch_path = folder / "one_leg_watch.json"
    saved = (
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders.WATCH_LOCK,
        live_lock_orders._send,
        live_lock_orders.fetch_book_ask,
        live_lock_orders.missed_market_closed,
        live_lock_orders._watch_ws_live,
        live_lock_orders._phone_watch_note,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        live_lock_orders.refresh_balances,
        live_lock_orders._append,
        live_lock_orders._read_orders,
        live_lock_orders._halt_logged,
    )
    live_lock_orders.ORDERS_STOP = flag
    live_lock_orders.ONE_LEG_WATCH = watch_path
    live_lock_orders.WATCH_LOCK = folder / "watch.lock"
    live_lock_orders._phone_watch_note = lambda *_a, **_k: None
    live_lock_orders._phone_order_placed = lambda *_a, **_k: None
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders.refresh_balances = lambda log=None: None
    live_lock_orders._append = lambda _row: None
    live_lock_orders._read_orders = lambda: []
    live_lock_orders.missed_market_closed = lambda _spec: (False, "open")
    live_lock_orders._watch_ws_live = lambda *_a, **_k: False
    live_lock_orders.fetch_book_ask = fetch_ask
    live_lock_orders._send = send
    live_lock_orders.ORDERS_ENABLED = False
    live_lock_orders._halt_logged = True
    flag.write_text(json.dumps({"stopped": True, "reason": "one leg filled and the other missed"}), encoding="utf-8")
    watch_path.write_text(json.dumps(watch), encoding="utf-8")
    return saved, flag, watch_path


def _restore_watch_harness(saved):
    live_lock_orders.ORDERS_ENABLED = saved[0]
    live_lock_orders.ORDERS_STOP = saved[1]
    live_lock_orders.ONE_LEG_WATCH = saved[2]
    live_lock_orders.WATCH_LOCK = saved[3]
    live_lock_orders._send = saved[4]
    live_lock_orders.fetch_book_ask = saved[5]
    live_lock_orders.missed_market_closed = saved[6]
    live_lock_orders._watch_ws_live = saved[7]
    live_lock_orders._phone_watch_note = saved[8]
    live_lock_orders._phone_order_placed = saved[9]
    live_lock_orders._refresh_order_pages = saved[10]
    live_lock_orders.refresh_balances = saved[11]
    live_lock_orders._append = saved[12]
    live_lock_orders._read_orders = saved[13]
    live_lock_orders._halt_logged = saved[14]


def _mtu_watch(**extra):
    row = {
        "bet_key": "k",
        "game": "Middle Tennessee vs FIU",
        "sport": "college football",
        "market_type": "total",
        "claim_side": "over",
        "number": "48.5",
        "started_at": "2026-10-20T19:32:10-04:00",
        "filled_venue": "kalshi",
        "filled_instrument": "KXNCAAFTOTAL-26OCT20MTUFIU-49",
        "filled_side": "no",
        "fill_px": "0.3300",
        "fill_fee": "0",
        "origin_venue": "kalshi",
        "opposite_side": "yes",
        "missed_venue": "gemini",
        "missed_instrument": "GEMI-NCAAF-2610202300-MTN-FIU-T-O48",
        "missed_side": "yes",
        "missed_intent": "",
        "max_other_price": "0.60",
        "watch_mode": "continuous_quote",
        "stopped": False,
        "venues": {
            "kalshi": {"instrument": "KXNCAAFTOTAL-26OCT20MTUFIU-49"},
            "gemini": {"instrument": "GEMI-NCAAF-2610202300-MTN-FIU-T-O48"},
            "polymarket": {"instrument": "cfb-mtu-fiu-total-48pt5"},
            "novig": {
                "instrument": "novig-mtu-fiu-48-5",
                "yes_outcome_id": "yes-oid",
                "no_outcome_id": "no-oid",
            },
        },
    }
    row.update(extra)
    return row


def test_watch_sequential_cheapest_stops_after_first_fill():
    import tempfile
    from pathlib import Path

    import novig_live

    folder = Path(tempfile.mkdtemp())
    sent = []

    def fetch_ask(spec, **_k):
        venue = str(spec.get("venue") or "")
        if venue == "kalshi":
            return Decimal("0.40"), "book"
        if venue == "gemini":
            return Decimal("0.40"), "book"
        if venue == "polymarket":
            return Decimal("0.50"), "book"
        if venue == "novig":
            return Decimal("0.30"), "book"
        return None, "missing"

    def fake_send(spec):
        sent.append(spec["venue"])
        filled = spec["venue"] == "kalshi"
        payload = {"status": "filled" if filled else "cancelled", "filledQuantity": "1" if filled else "0"}
        return 201, payload, "filled" if filled else "cancelled"

    saved_novig = novig_live.NOVIG_ORDERS_ENABLED
    novig_live.NOVIG_ORDERS_ENABLED = False
    saved, flag, watch_path = _watch_harness(folder, _mtu_watch(), fetch_ask, fake_send)
    saved_pin = _pin_balances("1000")
    try:
        status = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert status == "filled"
        assert sent == ["kalshi"]
        assert not flag.exists()
        assert not watch_path.exists()
        assert live_lock_orders.ORDERS_ENABLED is True
    finally:
        novig_live.NOVIG_ORDERS_ENABLED = saved_novig
        _unpin_balances(saved_pin)
        _restore_watch_harness(saved)


def test_watch_send_once_stops_after_miss():
    import tempfile
    from pathlib import Path

    import novig_live

    folder = Path(tempfile.mkdtemp())
    sent = []

    def fetch_ask(spec, **_k):
        venue = str(spec.get("venue") or "")
        if venue == "kalshi":
            return Decimal("0.40"), "book"
        if venue == "gemini":
            return Decimal("0.40"), "book"
        if venue == "novig":
            return Decimal("0.30"), "book"
        return Decimal("0.80"), "book"

    def fake_send(spec):
        sent.append(spec["venue"])
        return 201, {"status": "cancelled", "filledQuantity": "0"}, "cancelled"

    saved_novig = novig_live.NOVIG_ORDERS_ENABLED
    novig_live.NOVIG_ORDERS_ENABLED = False
    saved, flag, watch_path = _watch_harness(folder, _mtu_watch(), fetch_ask, fake_send)
    saved_pin = _pin_balances("1000")
    try:
        status = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert status == "miss"
        assert sent == ["kalshi"]
        assert "gemini" not in sent
        assert "novig" not in sent
        assert flag.exists()
        assert not live_lock_orders.watch_is_active()
        assert live_lock_orders.ORDERS_ENABLED is False
        status2 = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert status2 == "idle"
        assert sent == ["kalshi"]
    finally:
        novig_live.NOVIG_ORDERS_ENABLED = saved_novig
        _unpin_balances(saved_pin)
        _restore_watch_harness(saved)


def test_watch_partial_fill_does_not_retry():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    sent = []

    def fetch_ask(spec, **_k):
        if str(spec.get("venue") or "") == "kalshi":
            return Decimal("0.40"), "book"
        return Decimal("0.80"), "book"

    def fake_send(spec):
        sent.append(spec["venue"])
        return 201, {"status": "cancelled", "filledQuantity": "0.62", "remainingQuantity": "0.38"}, "cancelled"

    saved, flag, watch_path = _watch_harness(folder, _mtu_watch(), fetch_ask, fake_send)
    saved_pin = _pin_balances("1000")
    try:
        status = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert status == "partial"
        assert sent == ["kalshi"]
        assert flag.exists()
        assert not live_lock_orders.watch_is_active()
        assert live_lock_orders.ORDERS_ENABLED is False
        live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert sent == ["kalshi"]
    finally:
        _unpin_balances(saved_pin)
        _restore_watch_harness(saved)


def test_origin_404_keeps_watching_other_venues():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    sent = []

    def fetch_ask(spec, **_k):
        if str(spec.get("venue") or "") == "kalshi":
            return Decimal("0.20"), "book"
        if str(spec.get("venue") or "") == "polymarket":
            return None, "polymarket 404"
        return None, "missing"

    def fake_send(spec):
        sent.append(spec["venue"])
        return 201, {"status": "filled", "filledQuantity": "1"}, "filled"

    watch = {
        "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:WAW\t\tpolymarket\tkalshi",
        "game": "Wawrinka vs Landaluce",
        "sport": "tennis",
        "market_type": "moneyline",
        "claim_side": "Stan Wawrinka",
        "started_at": "2026-10-21T09:31:02-04:00",
        "filled_venue": "polymarket",
        "filled_instrument": "aec-atp-stawaw-marlan-2026-10-18",
        "filled_side": "yes",
        "fill_px": "0.700",
        "fill_fee": "0.01",
        "origin_venue": "polymarket",
        "opposite_side": "no",
        "missed_venue": "kalshi",
        "missed_instrument": "KXATPMATCH-26OCT18WAWLAN-WAW",
        "missed_side": "no",
        "max_other_price": "0.2400",
        "stopped": False,
        "venues": {
            "polymarket": {"instrument": "aec-atp-stawaw-marlan-2026-10-18"},
            "kalshi": {"instrument": "KXATPMATCH-26OCT18WAWLAN-WAW"},
        },
    }
    saved, flag, watch_path = _watch_harness(folder, watch, fetch_ask, fake_send)
    live_lock_orders.missed_market_closed = lambda spec: (
        (True, "polymarket 404") if spec.get("venue") == "polymarket" else (False, "open")
    )
    saved_pin = _pin_balances("1000")
    try:
        status = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert status == "filled"
        assert sent == ["kalshi"]
        assert live_lock_orders.ORDERS_ENABLED is True
        assert not watch_path.exists()
    finally:
        _unpin_balances(saved_pin)
        _restore_watch_harness(saved)


def test_persist_keeps_two_settlement_watches():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = live_lock_orders.ONE_LEG_WATCH
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    try:
        first = live_lock_orders.persist_one_leg_watch(
            "tennis\twawlan\t2026-10-18\tmoneyline\tcode:LAN\t\tpolymarket\tkalshi",
            "Wawrinka vs Landaluce",
            {"venue": "kalshi", "instrument": "KXATPMATCH-26OCT18WAWLAN-LAN", "outcome": "no"},
            {"venue": "polymarket", "instrument": "aec-atp-stawaw-marlan-2026-10-18", "outcome": "yes"},
            Decimal("0.66"),
            Decimal("0.016"),
        )
        second = live_lock_orders.persist_one_leg_watch(
            "tennis\twawlan\t2026-10-18\tmoneyline\tcode:WAW\t\tpolymarket\tkalshi",
            "Wawrinka vs Landaluce",
            {"venue": "polymarket", "instrument": "aec-atp-stawaw-marlan-2026-10-18", "outcome": "yes"},
            {"venue": "kalshi", "instrument": "KXATPMATCH-26OCT18WAWLAN-WAW", "outcome": "no"},
            Decimal("0.70"),
            Decimal("0.01"),
        )
        rows = live_lock_orders.load_all_watches()
        assert first is not None and second is not None
        assert len(rows) == 2
        keys = {row["bet_key"] for row in rows}
        assert first["bet_key"] in keys
        assert second["bet_key"] in keys
        assert live_lock_orders.watch_is_active()
    finally:
        live_lock_orders.ONE_LEG_WATCH = saved


def test_send_kalshi_fill_registers_watch_when_ledger_fails():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = (
        live_lock_orders.ORDERS,
        live_lock_orders.ORDER_IO,
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders._phone_order_placed,
        live_lock_orders._refresh_order_pages,
        live_lock_orders._complete_order_post,
        kalshi_private.signed_call,
    )

    def boom(*_args, **_kwargs):
        raise PermissionError("Access is denied")

    live_lock_orders.ORDERS = folder / "orders.jsonl"
    live_lock_orders.ORDER_IO = folder / "order_io.jsonl"
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders._phone_order_placed = lambda _spec: None
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders._complete_order_post = boom
    order_body = json.dumps({
        "average_fill_price": "0.3400",
        "fill_count": "1.00",
        "order_id": "oid-landaluce",
        "remaining_count": "0.00",
    })
    fills = json.dumps({
        "fills": [{
            "order_id": "oid-landaluce",
            "ticker": "KXATPMATCH-26OCT18WAWLAN-LAN",
            "count_fp": "1.00",
            "yes_price_dollars": "0.6600",
            "no_price_dollars": "0.3400",
            "outcome_side": "no",
        }],
        "cursor": "",
    })

    def fake_signed(method, path, body=None, query=None, timeout=30):
        if "portfolio/fills" in str(path):
            return 200, fills
        return 201, order_body

    kalshi_private.signed_call = fake_signed
    spec = {
        "venue": "kalshi",
        "instrument": "KXATPMATCH-26OCT18WAWLAN-LAN",
        "outcome": "no",
        "pay": "0.6900",
        "limit": "0.3100",
        "body": {"ticker": "KXATPMATCH-26OCT18WAWLAN-LAN", "side": "ask"},
        "_attempt": 1,
        "_bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:LAN\t\tpolymarket\tkalshi",
        "_step": "simultaneous",
    }
    try:
        status, payload, _note = live_lock_orders._send(spec)
        assert status == 201
        assert live_lock_orders.filled_contracts(payload) == Decimal("1.00")
        assert not live_lock_orders.watch_is_active()
        assert live_lock_orders.load_one_leg_watch() is None
    finally:
        live_lock_orders.ORDERS = saved[0]
        live_lock_orders.ORDER_IO = saved[1]
        live_lock_orders.ORDERS_ENABLED = saved[2]
        live_lock_orders.ORDERS_STOP = saved[3]
        live_lock_orders.ONE_LEG_WATCH = saved[4]
        live_lock_orders._phone_order_placed = saved[5]
        live_lock_orders._refresh_order_pages = saved[6]
        live_lock_orders._complete_order_post = saved[7]
        kalshi_private.signed_call = saved[8]


def test_do_not_leftover_watch_a_directional_dog():
    called = []
    saved = (
        live_lock_orders.persist_one_leg_watch,
        live_lock_orders.filled_contracts,
        live_lock_orders._actual_fill_cash,
        live_lock_orders.leg_fee,
    )
    live_lock_orders.persist_one_leg_watch = lambda *a, **_k: called.append(a[0] if a else "") or {"bet_key": a[0] if a else ""}
    live_lock_orders.filled_contracts = lambda _p: Decimal("1")
    live_lock_orders._actual_fill_cash = lambda *_a, **_k: Decimal("0.30")
    live_lock_orders.leg_fee = lambda *_a, **_k: Decimal("0.01")
    payload = {"fill_count": "1.00"}
    try:
        live_lock_orders._register_send_fill_watch(
            {
                "_system": "tennis_t0_dog",
                "_step": "e-t0",
                "_bet_key": "tennis-t0-dog\tromano",
                "venue": "polymarket",
                "instrument": "aec-romano",
                "outcome": "yes",
                "pay": "0.29",
            },
            payload,
        )
        live_lock_orders._register_send_fill_watch(
            {
                "_step": "e-t0",
                "_bet_key": "tennis-t0-dog\thumbert",
                "venue": "polymarket",
                "instrument": "aec-humbert",
                "outcome": "yes",
                "pay": "0.30",
            },
            payload,
        )
        live_lock_orders._register_send_fill_watch(
            {
                "_system": "cfb_favorite",
                "_step": "c-t0",
                "_bet_key": "cfb-favorite\ttroy",
                "venue": "kalshi",
                "instrument": "KXNCAAF",
                "outcome": "yes",
                "pay": "0.62",
            },
            payload,
        )
        live_lock_orders._register_send_fill_watch(
            {
                "_system": "spread_t0",
                "_step": "d-t0",
                "_bet_key": "spread-t0\ttbcar\t-3.5\t1",
                "venue": "kalshi",
                "instrument": "KXNCAAFSPREAD",
                "outcome": "yes",
                "pay": "0.58",
            },
            payload,
        )
        live_lock_orders._register_send_fill_watch(
            {
                "_system": "tennis_t0_spread",
                "_step": "f-t0",
                "_bet_key": "tennis-t0-spread\talcsin\tAlcaraz\t1.5\t1",
                "venue": "kalshi",
                "instrument": "KXATPMATCHSPREAD",
                "outcome": "yes",
                "pay": "0.31",
            },
            payload,
        )
        live_lock_orders._register_send_fill_watch(
            {
                "_system": "soccer_t0_total",
                "_step": "g-t0",
                "_bet_key": "soccer-t0-total\tarseche\tOver 2.5\t2.5\t1",
                "venue": "kalshi",
                "instrument": "KXEPLTOTAL",
                "outcome": "yes",
                "pay": "0.31",
            },
            payload,
        )
        assert called == []
        live_lock_orders._register_send_fill_watch(
            {
                "_step": "send",
                "_bet_key": "tennis\twawlan\t2026-10-18\tmoneyline",
                "venue": "kalshi",
                "instrument": "KXATPMATCH-26OCT18WAWLAN-LAN",
                "outcome": "yes",
                "pay": "0.40",
            },
            payload,
        )
        assert called == ["tennis\twawlan\t2026-10-18\tmoneyline"]
    finally:
        live_lock_orders.persist_one_leg_watch = saved[0]
        live_lock_orders.filled_contracts = saved[1]
        live_lock_orders._actual_fill_cash = saved[2]
        live_lock_orders.leg_fee = saved[3]


def test_lock_a_persist_still_opens_leftover_e_does_not():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = live_lock_orders.ONE_LEG_WATCH
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    filled = {"venue": "kalshi", "instrument": "KX-DOG", "outcome": "yes"}
    missed = {"venue": "polymarket", "instrument": "aec-fav", "outcome": "yes"}
    try:
        e_row = live_lock_orders.persist_one_leg_watch(
            "tennis-t0-dog\tdjokovic-musetti\tMusetti\t\t1",
            "Djokovic vs Musetti",
            {**filled, "_system": "tennis_t0_dog", "_step": "e-t0"},
            missed,
            Decimal("0.43"),
            Decimal("0.01"),
        )
        assert e_row is None
        assert not live_lock_orders.watch_is_active()
        lock_key = "tennis\tdjomus\t2026-10-28\tmoneyline\tcode:MUS\t\tkalshi\tpolymarket"
        lock_row = live_lock_orders.persist_one_leg_watch(
            lock_key,
            "Djokovic vs Musetti",
            filled,
            missed,
            Decimal("0.43"),
            Decimal("0.01"),
        )
        assert lock_row is not None
        assert lock_row["bet_key"] == lock_key
        assert live_lock_orders.watch_is_active()
    finally:
        live_lock_orders.ONE_LEG_WATCH = saved


def test_e_leftover_watch_does_not_send_55c_favorite():
    import tempfile
    from pathlib import Path

    import novig_live

    folder = Path(tempfile.mkdtemp())
    sent = []

    def fetch_ask(spec, **_k):
        return Decimal("0.55"), "book"

    def fake_send(spec):
        sent.append({"venue": spec.get("venue"), "pay": spec.get("pay"), "key": spec.get("_bet_key")})
        return 201, {"status": "filled", "filledQuantity": "1"}, "filled"

    watch = _mtu_watch(
        bet_key="tennis-t0-dog\tdjokovic-humbert\tHumbert\t\t1",
        game="Humbert vs Djokovic",
        fill_px="0.3000",
        fill_fee="0.01",
        filled_side="yes",
        opposite_side="no",
        missed_side="yes",
        max_other_price="0.65",
    )
    saved_novig = novig_live.NOVIG_ORDERS_ENABLED
    novig_live.NOVIG_ORDERS_ENABLED = False
    saved, _flag, watch_path = _watch_harness(folder, watch, fetch_ask, fake_send)
    saved_pin = _pin_balances("1000")
    try:
        status = live_lock_orders.tick_one_leg_watch(lambda *_a, **_k: None)
        assert status == "directional skip"
        assert sent == []
        stored = json.loads(watch_path.read_text(encoding="utf-8"))
        assert stored.get("stopped") is True
        assert not live_lock_orders.watch_is_active()
    finally:
        novig_live.NOVIG_ORDERS_ENABLED = saved_novig
        _unpin_balances(saved_pin)
        _restore_watch_harness(saved)


def test_onclin_hedge_skips_struff_no():
    watch = {
        "bet_key": "tennis\toncstr\t2026-10-21\tmoneyline\tcode:STR\t\tkalshi\tpolymarket",
        "game": "Onclin vs Struff",
        "filled_venue": "polymarket",
        "filled_instrument": "aec-atp-gauonc-janstr-2026-10-21",
        "filled_side": "yes",
        "missed_venue": "kalshi",
        "missed_instrument": "KXATPMATCH-26OCT21ONCSTR-STR",
        "missed_side": "yes",
        "opposite_side": "no",
        "venues": {
            "polymarket": {"instrument": "aec-atp-gauonc-janstr-2026-10-21"},
            "kalshi": {"instrument": "KXATPMATCH-26OCT21ONCSTR-STR"},
        },
    }
    specs = live_lock_orders.hedge_specs_from_watch(watch)
    keys = {(s["venue"], s["instrument"], s["outcome"]) for s in specs}
    assert ("kalshi", "KXATPMATCH-26OCT21ONCSTR-STR", "yes") in keys
    assert ("kalshi", "KXATPMATCH-26OCT21ONCSTR-STR", "no") not in keys
    assert ("polymarket", "aec-atp-gauonc-janstr-2026-10-21", "no") in keys
    assert ("polymarket", "aec-atp-gauonc-janstr-2026-10-21", "yes") not in keys


def test_watch_already_both_ignores_same_bet_no():
    watch = {
        "bet_key": "k-onclin",
        "filled_venue": "polymarket",
        "filled_instrument": "aec-atp-gauonc-janstr-2026-10-21",
        "filled_side": "yes",
        "missed_venue": "kalshi",
        "missed_instrument": "KXATPMATCH-26OCT21ONCSTR-STR",
        "missed_side": "yes",
        "opposite_side": "no",
        "venues": {
            "polymarket": {"instrument": "aec-atp-gauonc-janstr-2026-10-21"},
            "kalshi": {"instrument": "KXATPMATCH-26OCT21ONCSTR-STR"},
        },
    }
    rows = [
        {"event": "filled", "bet_key": "k-onclin", "venue": "polymarket", "instrument": "aec-atp-gauonc-janstr-2026-10-21", "side": "yes"},
        {"event": "filled", "bet_key": "k-onclin", "venue": "kalshi", "instrument": "KXATPMATCH-26OCT21ONCSTR-STR", "side": "no"},
    ]
    saved = live_lock_orders._read_orders
    live_lock_orders._read_orders = lambda: rows
    try:
        assert live_lock_orders._watch_already_both(watch) is False
        rows.append({
            "event": "filled", "bet_key": "k-onclin",
            "venue": "kalshi", "instrument": "KXATPMATCH-26OCT21ONCSTR-STR", "side": "yes",
        })
        assert live_lock_orders._watch_already_both(watch) is True
    finally:
        live_lock_orders._read_orders = saved


def test_kalshi_201_fill_count_zero_is_not_a_fill():
    empty = {"status": "cancelled", "fill_count": "0.00", "remaining_count": "0.00"}
    executed_empty = {"status": "executed", "fill_count": "0.00"}
    assert live_lock_orders.filled_contracts(empty) == Decimal("0")
    assert live_lock_orders.filled_contracts(executed_empty) == Decimal("0")
    assert live_lock_orders.leg_filled_at_least_one({
        "payload": empty, "filled": True, "status": 201, "fill_qty": "0",
    }) is False
    assert live_lock_orders.leg_filled_at_least_one({
        "payload": executed_empty, "filled": True, "status": 201,
    }) is False
    assert live_lock_orders.ioc_nothing_filled(201, empty)


def test_weak_filled_flag_without_qty_is_not_a_fill():
    assert live_lock_orders.leg_filled_at_least_one({
        "filled": True, "payload": None, "status": 201, "posted": True,
    }) is False
    assert live_lock_orders.leg_filled_at_least_one({
        "filled": True, "payload": {"status": "cancelled"}, "status": 201,
    }) is False
    real = {"average_fill_price": "0.3400", "fill_count": "1.00"}
    assert live_lock_orders.leg_filled_at_least_one({
        "payload": real, "filled": False, "status": 201,
    })


def test_status_filled_without_qty_is_not_a_fill():
    """HTTP 201 + status filled with no contracts is unknown, not a lock fill.

    21 Oct 2026 SHSU 9.5 at 22:58:48 — opportunities said one-leg + Gemini flatten
    miss. Kalshi IOC fill_count 0 and Gemini 'no part of the order would be filled'
    are both zero.
    """
    assert live_lock_orders.filled_contracts({"status": "filled"}) == Decimal("0")
    assert live_lock_orders.filled_contracts({"status": "executed"}) == Decimal("0")
    assert live_lock_orders.filled_contracts({"status": "complete"}) == Decimal("0")
    assert live_lock_orders.leg_filled_at_least_one({
        "filled": True, "payload": {"status": "filled"}, "status": 201, "posted": True,
    }) is False
    gemini_email = {
        "status": "canceled",
        "filledQuantity": "0",
        "reason": (
            "Your limit buy because the order was submitted with the execution "
            "option Immediate Or Cancel but no part of the order would be filled "
            "immediately has been canceled."
        ),
    }
    assert live_lock_orders.filled_contracts(gemini_email) == Decimal("0")
    assert live_lock_orders.leg_filled_at_least_one({
        "payload": gemini_email, "filled": True, "status": 201, "posted": True,
    }) is False
    kalshi_empty = {"status": "cancelled", "fill_count": "0.00", "remaining_count": "0.00"}
    assert live_lock_orders.exactly_one_leg_filled(
        {"payload": kalshi_empty, "filled": True, "status": 201},
        {"payload": gemini_email, "filled": True, "status": 201},
    ) is False


def test_send_pair_does_not_log_both_filled_on_empty_201():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    seen = []
    kalshi = {"venue": "kalshi", "outcome": "yes", "pay": "0.4000", "instrument": "KX-SHSU10", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.4000"}
    gemini = {"venue": "gemini", "outcome": "no", "pay": "0.50", "instrument": "G-SHS10", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.50"}
    saved = (
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders.WATCH_LOCK,
        live_lock_orders.LAST_SKIP,
        live_lock_orders.fetch_book_ask,
        live_lock_orders._one_ioc,
        live_lock_orders._append,
        live_lock_orders._profit_block,
        live_lock_orders._funds_block,
        live_lock_orders._spec_at_price,
        live_lock_orders._phone_trade_result,
        live_lock_orders._refresh_order_pages,
        live_lock_orders._log_consider,
        live_lock_orders.refresh_balances,
        live_lock_orders.place_leg,
    )

    def fake_spec(spec, pay):
        built = dict(spec)
        built["pay"] = format(pay, "f") if hasattr(pay, "quantize") else str(pay)
        built["limit"] = built["pay"]
        built["body"] = built.get("body") or {"price": built["pay"]}
        return built

    def empty_201(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
        venue = str(spec.get("venue") or "")
        if venue == "gemini":
            payload = {
                "status": "canceled",
                "filledQuantity": "0",
                "reason": (
                    "Your limit buy because the order was submitted with the execution option "
                    "Immediate Or Cancel but no part of the order would be filled immediately "
                    "has been canceled."
                ),
            }
            note = payload["reason"]
        else:
            payload = {"status": "cancelled", "fill_count": "0.00", "filledQuantity": "0"}
            note = "cancelled"
        return {
            "filled": True,
            "payload": payload,
            "status": 201,
            "note": note,
            "pay": spec.get("pay"),
            "spec": spec,
            "step": step,
            "posted": True,
            "fill_qty": "0",
        }

    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    live_lock_orders.WATCH_LOCK = folder / "watch.lock"
    live_lock_orders.LAST_SKIP = folder / "lock_last_skip.json"
    live_lock_orders._append = lambda _row: None
    live_lock_orders._profit_block = lambda *_a, **_k: ""
    live_lock_orders._funds_block = lambda _built: ""
    live_lock_orders._phone_trade_result = lambda *_a, **_k: None
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders.refresh_balances = lambda log=None: None
    live_lock_orders.place_leg = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("recovery not expected"))

    def capture(decision, reason, net=None, cand_patch=None):
        seen.append(f"{decision}:{reason}")
        if isinstance(cand_patch, dict) and cand_patch.get("venue_return"):
            seen.append("venue:" + str(cand_patch.get("venue_return")))

    live_lock_orders._log_consider = capture
    live_lock_orders._spec_at_price = fake_spec

    def fake_book(spec, **_k):
        live_lock_orders._attach_quote_size(spec, "10")
        pay = live_lock_orders._dec(spec.get("pay")) or Decimal("0.40")
        return pay, "book"

    live_lock_orders.fetch_book_ask = fake_book
    live_lock_orders._one_ioc = empty_201
    try:
        live_lock_orders._send_pair(lambda *_a, **_k: None, "k-shsu95", "New Mexico State vs Sam Houston", [kalshi, gemini])
        assert not any("Both legs filled" in item for item in seen)
        sent = next(item for item in seen if item.startswith("sent:"))
        assert "Hard miss abort" in sent
        assert "Did not send the easier leg" in sent
        assert "gemini HTTP 201 fill 0" in sent
        assert "no part of the order would be filled" in sent
        assert "kalshi HTTP" not in sent
        venue_line = next(item for item in seen if item.startswith("venue:"))
        assert "gemini HTTP 201 fill 0" in venue_line
        assert "no part of the order would be filled" in venue_line
        assert not any("One leg filled" in item for item in seen)
        assert not live_lock_orders.ORDERS_STOP.exists()
        assert not live_lock_orders.ONE_LEG_WATCH.exists()
    finally:
        live_lock_orders.ORDERS_ENABLED = saved[0]
        live_lock_orders.ORDERS_STOP = saved[1]
        live_lock_orders.ONE_LEG_WATCH = saved[2]
        live_lock_orders.WATCH_LOCK = saved[3]
        live_lock_orders.LAST_SKIP = saved[4]
        live_lock_orders.fetch_book_ask = saved[5]
        live_lock_orders._one_ioc = saved[6]
        live_lock_orders._append = saved[7]
        live_lock_orders._profit_block = saved[8]
        live_lock_orders._funds_block = saved[9]
        live_lock_orders._spec_at_price = saved[10]
        live_lock_orders._phone_trade_result = saved[11]
        live_lock_orders._refresh_order_pages = saved[12]
        live_lock_orders._log_consider = saved[13]
        live_lock_orders.refresh_balances = saved[14]
        live_lock_orders.place_leg = saved[15]


def test_send_pair_status_filled_without_qty_is_both_unfilled():
    """Gemini HTTP 201 status=filled with no qty + Kalshi fill_count 0 is both_unfilled.

    Must not flatten, latch, or log one-leg (21 Oct 2026 SHSU 9.5 22:58:48).
    """
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    seen = []
    kalshi = {"venue": "kalshi", "outcome": "yes", "pay": "0.4000", "instrument": "KX-SHSU10", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.4000"}
    gemini = {"venue": "gemini", "outcome": "no", "pay": "0.50", "instrument": "G-SHS10", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.50"}
    saved = (
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders.WATCH_LOCK,
        live_lock_orders.LAST_SKIP,
        live_lock_orders.fetch_book_ask,
        live_lock_orders._one_ioc,
        live_lock_orders._append,
        live_lock_orders._profit_block,
        live_lock_orders._funds_block,
        live_lock_orders._spec_at_price,
        live_lock_orders._phone_trade_result,
        live_lock_orders._refresh_order_pages,
        live_lock_orders._log_consider,
        live_lock_orders.refresh_balances,
        live_lock_orders.place_leg,
        live_lock_orders.flatten_filled_leg,
    )

    def fake_spec(spec, pay):
        built = dict(spec)
        built["pay"] = format(pay, "f") if hasattr(pay, "quantize") else str(pay)
        built["limit"] = built["pay"]
        built["body"] = built.get("body") or {"price": built["pay"]}
        return built

    def mixed_201(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
        if str(spec.get("venue") or "") == "gemini":
            payload = {"status": "filled"}
            note = "flatten miss"
        else:
            payload = {"status": "cancelled", "fill_count": "0.00", "remaining_count": "0.00"}
            note = "cancelled"
        return {
            "filled": True,
            "payload": payload,
            "status": 201,
            "note": note,
            "pay": spec.get("pay"),
            "spec": spec,
            "step": step,
            "posted": True,
            "fill_qty": "0",
        }

    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    live_lock_orders.WATCH_LOCK = folder / "watch.lock"
    live_lock_orders.LAST_SKIP = folder / "lock_last_skip.json"
    live_lock_orders._append = lambda _row: None
    live_lock_orders._profit_block = lambda *_a, **_k: ""
    live_lock_orders._funds_block = lambda _built: ""
    live_lock_orders._phone_trade_result = lambda *_a, **_k: None
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders.refresh_balances = lambda log=None: None
    live_lock_orders.place_leg = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("recovery not expected"))
    live_lock_orders.flatten_filled_leg = lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("flatten not expected when filled_contracts is 0")
    )
    live_lock_orders._log_consider = lambda decision, reason, *a, **k: seen.append(f"{decision}:{reason}")
    live_lock_orders._spec_at_price = fake_spec

    def fake_book(spec, **_k):
        live_lock_orders._attach_quote_size(spec, "10")
        pay = live_lock_orders._dec(spec.get("pay")) or Decimal("0.40")
        return pay, "book"

    live_lock_orders.fetch_book_ask = fake_book
    live_lock_orders._one_ioc = mixed_201
    try:
        live_lock_orders._send_pair(lambda *_a, **_k: None, "k-shsu95-2258", "New Mexico State vs Sam Houston", [kalshi, gemini])
        assert any("Hard miss abort" in item for item in seen)
        assert not any("One leg filled" in item for item in seen)
        assert not any("Both legs filled" in item for item in seen)
        assert not live_lock_orders.ORDERS_STOP.exists()
        assert not live_lock_orders.ONE_LEG_WATCH.exists()
    finally:
        live_lock_orders.ORDERS_ENABLED = saved[0]
        live_lock_orders.ORDERS_STOP = saved[1]
        live_lock_orders.ONE_LEG_WATCH = saved[2]
        live_lock_orders.WATCH_LOCK = saved[3]
        live_lock_orders.LAST_SKIP = saved[4]
        live_lock_orders.fetch_book_ask = saved[5]
        live_lock_orders._one_ioc = saved[6]
        live_lock_orders._append = saved[7]
        live_lock_orders._profit_block = saved[8]
        live_lock_orders._funds_block = saved[9]
        live_lock_orders._spec_at_price = saved[10]
        live_lock_orders._phone_trade_result = saved[11]
        live_lock_orders._refresh_order_pages = saved[12]
        live_lock_orders._log_consider = saved[13]
        live_lock_orders.refresh_balances = saved[14]
        live_lock_orders.place_leg = saved[15]
        live_lock_orders.flatten_filled_leg = saved[16]


def test_record_sent_same_second_does_not_stack_quote_patches():
    import opportunity_considerations
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = (
        opportunity_considerations.LOG_PATH,
        opportunity_considerations.LOCK_PATH,
        opportunity_considerations.write_page,
        opportunity_considerations._schedule_page,
    )
    opportunity_considerations.LOG_PATH = folder / "considerations.json"
    opportunity_considerations.LOCK_PATH = folder / "considerations.lock"
    opportunity_considerations.write_page = lambda: None
    opportunity_considerations._schedule_page = lambda: None
    opportunity_considerations._mem_fp.clear()
    at = "2026-10-21T22:42:05-04:00"
    cand = {
        "market_type": "spread",
        "side": "Sam Houston",
        "number": "9.5",
        "yes_venue": "kalshi",
        "no_venue": "gemini",
        "yes_price": "0.4000",
        "no_price": "0.400",
        "yes_size": "2",
        "no_size": "2",
    }
    try:
        assert opportunity_considerations.record(
            "college football", "New Mexico State vs Sam Houston", cand, "sent",
            "Both legs filled.", Decimal("0.95"), at=at,
        )
        second = dict(cand)
        second["no_price"] = "0.53"
        assert opportunity_considerations.record(
            "college football", "New Mexico State vs Sam Houston", second, "sent",
            "Both legs filled.", Decimal("0.95"), at=at,
        ) is False
        third = dict(cand)
        third["no_price"] = "0.50"
        assert opportunity_considerations.record(
            "college football", "New Mexico State vs Sam Houston", third, "sent",
            "Neither leg filled.", Decimal("0.95"), at=at,
        ) is False
        rows = json.loads((folder / "considerations.json").read_text(encoding="utf-8"))["rows"]
        assert len(rows) == 1
        assert rows[0]["reason"] == "Both legs filled."
        assert rows[0]["no_price"] == "0.400"
    finally:
        opportunity_considerations.LOG_PATH = saved[0]
        opportunity_considerations.LOCK_PATH = saved[1]
        opportunity_considerations.write_page = saved[2]
        opportunity_considerations._schedule_page = saved[3]


def test_public_note_kalshi_201_fill_count_zero_is_cancel_text():
    kalshi_body = json.dumps({"status": "cancelled", "fill_count": "0.00", "remaining_count": "0.00"})
    note = live_lock_orders._public_note(kalshi_body)
    assert "cancelled" in note
    assert "fill_count 0" in note
    nested = json.dumps({"order": {"status": "cancelled", "fill_count": "0.00"}})
    nested_note = live_lock_orders._public_note(nested)
    assert "cancelled" in nested_note
    assert "fill_count 0" in nested_note
    gemini_body = json.dumps({
        "status": "canceled",
        "filledQuantity": "0",
        "reason": (
            "Your limit buy because the order was submitted with the execution option "
            "Immediate Or Cancel but no part of the order would be filled immediately "
            "has been canceled."
        ),
        "signature": "should-not-appear",
    })
    gnote = live_lock_orders._public_note(gemini_body)
    assert "no part of the order would be filled" in gnote.lower()
    assert "should-not-appear" not in gnote
    assert "signature" not in gnote.lower()
    assert live_lock_orders._public_note(json.dumps({"reason": "bad signature xyz"})) == "rejected"
    kalshi_out = {
        "posted": True, "status": 201, "fill_qty": "0", "note": "cancelled",
        "payload": {"status": "cancelled", "fill_count": "0.00"},
        "spec": {"venue": "kalshi", "outcome": "yes"},
        "step": "simultaneous",
    }
    line = live_lock_orders.format_posted_leg_return(kalshi_out)
    assert "kalshi HTTP 201 fill 0" in line
    assert "cancelled" in line
    assert "fill_count 0" in line
    assert "Both legs filled" not in line
    reason = live_lock_orders.sent_reason_with_venue_returns("Neither leg filled.", kalshi_out)
    assert reason.startswith("Neither leg filled.")
    assert "kalshi HTTP 201 fill 0" in reason
    assert "Both legs filled" not in reason


def test_opportunities_page_shows_venue_return_on_sent_row():
    import opportunity_considerations
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = (
        opportunity_considerations.LOG_PATH,
        opportunity_considerations.LOCK_PATH,
        opportunity_considerations.PAGE,
        opportunity_considerations._schedule_page,
    )
    opportunity_considerations.LOG_PATH = folder / "considerations.json"
    opportunity_considerations.LOCK_PATH = folder / "considerations.lock"
    opportunity_considerations.PAGE = folder / "opportunities.html"
    opportunity_considerations._schedule_page = lambda: None
    opportunity_considerations._mem_fp.clear()
    cand = {
        "market_type": "spread",
        "side": "Sam Houston",
        "number": "9.5",
        "yes_venue": "kalshi",
        "no_venue": "gemini",
        "yes_price": "0.4000",
        "no_price": "0.50",
        "yes_size": "2",
        "no_size": "2",
        "venue_return": (
            "kalshi HTTP 201 fill 0 cancelled fill_count 0. "
            "gemini HTTP 201 fill 0 canceled no part of the order would be filled immediately."
        ),
    }
    reason = (
        "Neither leg filled. kalshi HTTP 201 fill 0 cancelled fill_count 0. "
        "gemini HTTP 201 fill 0 canceled no part of the order would be filled immediately."
    )
    try:
        assert opportunity_considerations.record(
            "college football", "New Mexico State vs Sam Houston", cand, "sent",
            reason, Decimal("0.95"), at="2026-10-21T22:42:05-04:00",
        )
        page = (folder / "opportunities.html").read_text(encoding="utf-8")
        assert "Leg 1 fill?" in page
        assert "Flatten P&amp;L" in page or "Flatten P&L" in page
        assert "Outcome" in page
        assert 'data-sort="text"' in page
        assert "sortable-th" in page
        assert "miss 0" in page
        assert "both miss" in page
        assert "Both legs filled" not in page
        assert "Venue return" not in page
        assert "from NET_MAX" in page
        rows = json.loads((folder / "considerations.json").read_text(encoding="utf-8"))["rows"]
        assert rows[0]["venue_return"].startswith("kalshi HTTP 201 fill 0")
        assert rows[0]["reason"].startswith("Neither leg filled.")
    finally:
        opportunity_considerations.LOG_PATH = saved[0]
        opportunity_considerations.LOCK_PATH = saved[1]
        opportunity_considerations.PAGE = saved[2]
        opportunity_considerations._schedule_page = saved[3]


def test_ghost_overlay_strikes_mixed_tbcar_nms_sent():
    import opportunity_considerations
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = (
        opportunity_considerations.LOG_PATH,
        opportunity_considerations.LOCK_PATH,
        opportunity_considerations.PAGE,
        opportunity_considerations._schedule_page,
    )
    opportunity_considerations.LOG_PATH = folder / "considerations.json"
    opportunity_considerations.LOCK_PATH = folder / "considerations.lock"
    opportunity_considerations.PAGE = folder / "opportunities.html"
    opportunity_considerations._schedule_page = lambda: None
    opportunity_considerations._mem_fp.clear()
    cand = _nmsu_under_send_line()
    cand["venue_return"] = (
        "kalshi HTTP 201 fill 1 filled. polymarket HTTP 201 fill 1 filled."
    )
    try:
        wrote = opportunity_considerations.record(
            "pro football",
            "Tampa Bay vs Carolina",
            cand,
            "sent",
            "Both legs filled. kalshi HTTP 201 fill 1 filled. polymarket HTTP 201 fill 1 filled.",
            Decimal("0.98392"),
            at="2026-10-26T18:37:39.168-04:00",
        )
        assert wrote
        rows = json.loads((folder / "considerations.json").read_text(encoding="utf-8"))["rows"]
        assert rows[0]["decision"] == "denied"
        assert rows[0]["ghost"] is True
        assert rows[0]["reason"].startswith("False sent (ghost).")
        opportunity_considerations.write_page()
        page = (folder / "opportunities.html").read_text(encoding="utf-8")
        assert "False sent (ghost)" in page
        assert ">denied<" in page
        struck, again = opportunity_considerations.strike_mixed_ghosts(rows)
        assert struck == 0
        assert again[0]["decision"] == "denied"
    finally:
        opportunity_considerations.LOG_PATH = saved[0]
        opportunity_considerations.LOCK_PATH = saved[1]
        opportunity_considerations.PAGE = saved[2]
        opportunity_considerations._schedule_page = saved[3]
        opportunity_considerations._mem_fp.clear()


def test_send_gate_skips_empty_other_book():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    kalshi = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "instrument": "KX", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.40"}
    gemini = {"venue": "gemini", "outcome": "no", "pay": "0.50", "instrument": "G", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.50"}
    sent = []
    saved = (
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders.WATCH_LOCK,
        live_lock_orders.LAST_SKIP,
        live_lock_orders.fetch_book_ask,
        live_lock_orders._one_ioc,
        live_lock_orders._append,
        live_lock_orders._profit_block,
        live_lock_orders._funds_block,
        live_lock_orders._spec_at_price,
        live_lock_orders._phone_trade_result,
        live_lock_orders._refresh_order_pages,
        live_lock_orders._log_consider,
    )
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    live_lock_orders.WATCH_LOCK = folder / "watch.lock"
    live_lock_orders.LAST_SKIP = folder / "lock_last_skip.json"
    live_lock_orders._append = lambda _row: None
    live_lock_orders._profit_block = lambda *_a, **_k: ""
    live_lock_orders._funds_block = lambda _built: ""
    live_lock_orders._phone_trade_result = lambda *_a, **_k: None
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders._log_consider = lambda *_a, **_k: None

    def fake_spec(spec, pay):
        built = dict(spec)
        built["pay"] = format(pay, "f") if hasattr(pay, "quantize") else str(pay)
        built["limit"] = built["pay"]
        built["body"] = built.get("body") or {"price": built["pay"]}
        return built

    def fake_book(spec, **_k):
        if spec.get("venue") == "kalshi":
            live_lock_orders._attach_quote_size(spec, "10")
            return Decimal("0.40"), "book"
        return None, "empty"

    live_lock_orders._spec_at_price = fake_spec
    live_lock_orders.fetch_book_ask = fake_book
    live_lock_orders._one_ioc = lambda *_a, **_k: sent.append("sent") or {"filled": False, "posted": False, "status": 0, "note": "no", "spec": {}, "step": "simultaneous"}
    try:
        live_lock_orders._send_pair(lambda *_a, **_k: None, "k", "Game", [kalshi, gemini])
        assert sent == []
        skip = json.loads(live_lock_orders.LAST_SKIP.read_text(encoding="utf-8"))
        assert "empty" in str(skip.get("reason") or "").lower() or "gemini" in str(skip.get("reason") or "").lower()
    finally:
        live_lock_orders.ORDERS_ENABLED = saved[0]
        live_lock_orders.ORDERS_STOP = saved[1]
        live_lock_orders.ONE_LEG_WATCH = saved[2]
        live_lock_orders.WATCH_LOCK = saved[3]
        live_lock_orders.LAST_SKIP = saved[4]
        live_lock_orders.fetch_book_ask = saved[5]
        live_lock_orders._one_ioc = saved[6]
        live_lock_orders._append = saved[7]
        live_lock_orders._profit_block = saved[8]
        live_lock_orders._funds_block = saved[9]
        live_lock_orders._spec_at_price = saved[10]
        live_lock_orders._phone_trade_result = saved[11]
        live_lock_orders._refresh_order_pages = saved[12]
        live_lock_orders._log_consider = saved[13]


def test_pick_hard_leg_smaller_size_then_venue_then_price():
    thin = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "quote_size": "1"}
    thick = {"venue": "gemini", "outcome": "no", "pay": "0.50", "quote_size": "10"}
    hard, easy = live_lock_orders._pick_hard_leg(thin, thick)
    assert hard is thin and easy is thick
    hard, easy = live_lock_orders._pick_hard_leg(thick, thin)
    assert hard is thin and easy is thick
    a = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "quote_size": "5"}
    b = {"venue": "gemini", "outcome": "no", "pay": "0.50", "quote_size": "5"}
    hard, easy = live_lock_orders._pick_hard_leg(a, b)
    assert hard is b and easy is a
    c = {"venue": "kalshi", "outcome": "yes", "pay": "0.60", "quote_size": "5"}
    d = {"venue": "kalshi", "outcome": "no", "pay": "0.30", "quote_size": "5"}
    hard, easy = live_lock_orders._pick_hard_leg(c, d)
    assert hard is c and easy is d


def _hard_first_harness(folder, kalshi, gemini, fake_book, one_ioc):
    saved = (
        live_lock_orders.ORDERS_ENABLED,
        live_lock_orders.ORDERS_STOP,
        live_lock_orders.ONE_LEG_WATCH,
        live_lock_orders.WATCH_LOCK,
        live_lock_orders.LAST_SKIP,
        live_lock_orders.fetch_book_ask,
        live_lock_orders._one_ioc,
        live_lock_orders._append,
        live_lock_orders._profit_block,
        live_lock_orders._funds_block,
        live_lock_orders._spec_at_price,
        live_lock_orders._phone_trade_result,
        live_lock_orders._refresh_order_pages,
        live_lock_orders._log_consider,
        live_lock_orders.refresh_balances,
        live_lock_orders.place_leg,
        live_lock_orders.flatten_filled_leg,
        live_lock_orders.alert_one_leg,
        live_lock_orders._phone_orders_off,
        live_lock_orders._phone_watch_note,
    )

    def fake_spec(spec, pay):
        built = dict(spec)
        built["pay"] = format(pay, "f") if hasattr(pay, "quantize") else str(pay)
        built["limit"] = built["pay"]
        built["body"] = built.get("body") or {"price": built["pay"]}
        return built

    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.ORDERS_STOP = folder / "orders_stopped.json"
    live_lock_orders.ONE_LEG_WATCH = folder / "one_leg_watch.json"
    live_lock_orders.WATCH_LOCK = folder / "watch.lock"
    live_lock_orders.LAST_SKIP = folder / "lock_last_skip.json"
    live_lock_orders._append = lambda _row: None
    live_lock_orders._profit_block = lambda *_a, **_k: ""
    live_lock_orders._funds_block = lambda _built: ""
    live_lock_orders._phone_trade_result = lambda *_a, **_k: None
    live_lock_orders._refresh_order_pages = lambda: None
    live_lock_orders._log_consider = lambda *_a, **_k: None
    live_lock_orders.refresh_balances = lambda log=None: None
    live_lock_orders.place_leg = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("recovery not expected"))
    live_lock_orders.alert_one_leg = lambda *_a, **_k: None
    live_lock_orders._phone_orders_off = lambda *_a, **_k: None
    live_lock_orders._phone_watch_note = lambda *_a, **_k: None
    live_lock_orders._spec_at_price = fake_spec
    live_lock_orders.fetch_book_ask = fake_book
    live_lock_orders._one_ioc = one_ioc
    return saved


def _restore_hard_first(saved):
    live_lock_orders.ORDERS_ENABLED = saved[0]
    live_lock_orders.ORDERS_STOP = saved[1]
    live_lock_orders.ONE_LEG_WATCH = saved[2]
    live_lock_orders.WATCH_LOCK = saved[3]
    live_lock_orders.LAST_SKIP = saved[4]
    live_lock_orders.fetch_book_ask = saved[5]
    live_lock_orders._one_ioc = saved[6]
    live_lock_orders._append = saved[7]
    live_lock_orders._profit_block = saved[8]
    live_lock_orders._funds_block = saved[9]
    live_lock_orders._spec_at_price = saved[10]
    live_lock_orders._phone_trade_result = saved[11]
    live_lock_orders._refresh_order_pages = saved[12]
    live_lock_orders._log_consider = saved[13]
    live_lock_orders.refresh_balances = saved[14]
    live_lock_orders.place_leg = saved[15]
    live_lock_orders.flatten_filled_leg = saved[16]
    live_lock_orders.alert_one_leg = saved[17]
    live_lock_orders._phone_orders_off = saved[18]
    live_lock_orders._phone_watch_note = saved[19]


def test_hard_miss_does_not_send_easy():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    ioc_steps = []
    kalshi = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "instrument": "KX", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.40"}
    gemini = {"venue": "gemini", "outcome": "no", "pay": "0.50", "instrument": "G", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.50"}

    def fake_book(spec, **_k):
        venue = str(spec.get("venue") or "")
        live_lock_orders._attach_quote_size(spec, "1" if venue == "kalshi" else "10")
        pay = live_lock_orders._dec(spec.get("pay")) or Decimal("0.40")
        return pay, "book"

    def miss_ioc(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
        ioc_steps.append((spec["venue"], step))
        return {
            "filled": False,
            "payload": {"status": "cancelled", "fill_count": "0.00"},
            "status": 201,
            "note": "cancelled",
            "pay": spec.get("pay"),
            "spec": spec,
            "step": step,
            "posted": True,
        }

    saved = _hard_first_harness(folder, kalshi, gemini, fake_book, miss_ioc)
    events = []
    live_lock_orders._append = lambda row: events.append(row)
    try:
        live_lock_orders._send_pair(lambda *_a, **_k: None, "k", "Game", [kalshi, gemini])
        assert ioc_steps == [("kalshi", "hard")]
        assert any(row.get("event") == "hard_miss_abort" for row in events)
        assert not live_lock_orders.ORDERS_STOP.exists()
        assert not live_lock_orders.ONE_LEG_WATCH.exists()
    finally:
        _restore_hard_first(saved)


def test_hard_fill_gap_closed_flattens_not_second_send():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    ioc_steps = []
    flatten_calls = []
    kalshi = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "instrument": "KX", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.40"}
    gemini = {"venue": "gemini", "outcome": "no", "pay": "0.50", "instrument": "G", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.50"}
    book_calls = {"n": 0}

    def fake_book(spec, **_k):
        book_calls["n"] += 1
        venue = str(spec.get("venue") or "")
        if book_calls["n"] <= 2:
            live_lock_orders._attach_quote_size(spec, "1" if venue == "kalshi" else "10")
            pay = live_lock_orders._dec(spec.get("pay")) or Decimal("0.40")
            return pay, "book"
        return None, "empty"

    def one_ioc(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
        ioc_steps.append((spec["venue"], step))
        filled = step == "hard"
        if step == "flatten":
            flatten_calls.append(spec["venue"])
        return {
            "filled": filled,
            "payload": {"status": "filled" if filled else "cancelled", "filledQuantity": "1" if filled else "0"},
            "status": 201,
            "note": "filled" if filled else "flatten miss",
            "pay": spec.get("pay"),
            "spec": spec,
            "step": step,
            "posted": True,
        }

    saved = _hard_first_harness(folder, kalshi, gemini, fake_book, one_ioc)
    live_lock_orders.flatten_filled_leg = lambda log, key, title, filled_spec: one_ioc(
        log, key, live_lock_orders._flatten_spec(filled_spec) or filled_spec, Decimal("0.50"), "flatten", None
    )
    try:
        live_lock_orders._send_pair(lambda *_a, **_k: None, "k", "Game", [kalshi, gemini])
        assert ioc_steps[0] == ("kalshi", "hard")
        assert ("gemini", "easy") not in ioc_steps
        assert flatten_calls == ["kalshi"]
    finally:
        _restore_hard_first(saved)


def test_hard_fill_gap_open_sends_easy():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    ioc_steps = []
    kalshi = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "instrument": "KX", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.40"}
    gemini = {"venue": "gemini", "outcome": "no", "pay": "0.50", "instrument": "G", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.50"}

    def fake_book(spec, **_k):
        venue = str(spec.get("venue") or "")
        live_lock_orders._attach_quote_size(spec, "1" if venue == "kalshi" else "10")
        pay = live_lock_orders._dec(spec.get("pay")) or Decimal("0.40")
        return pay, "book"

    def both_ioc(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
        ioc_steps.append((spec["venue"], step))
        return {
            "filled": True,
            "payload": {"status": "filled", "filledQuantity": "1"},
            "status": 201,
            "note": "filled",
            "pay": spec.get("pay"),
            "spec": spec,
            "step": step,
            "posted": True,
        }

    saved = _hard_first_harness(folder, kalshi, gemini, fake_book, both_ioc)
    try:
        live_lock_orders._send_pair(lambda *_a, **_k: None, "k", "Game", [kalshi, gemini])
        assert ioc_steps == [("kalshi", "hard"), ("gemini", "easy")]
        assert not live_lock_orders.ORDERS_STOP.exists()
    finally:
        _restore_hard_first(saved)


def test_send_pair_defers_html_until_after_both_ioc():
    """Hard confirm must not rewrite Drive HTML before the easy IOC leaves."""
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    timeline = []
    scheduled = []
    kalshi = {"venue": "kalshi", "outcome": "yes", "pay": "0.40", "instrument": "KX", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.40"}
    gemini = {"venue": "gemini", "outcome": "no", "pay": "0.50", "instrument": "G", "intent": "", "fee_coefficient": None, "body": {}, "limit": "0.50"}

    def fake_book(spec, **_k):
        venue = str(spec.get("venue") or "")
        live_lock_orders._attach_quote_size(spec, "1" if venue == "kalshi" else "10")
        pay = live_lock_orders._dec(spec.get("pay")) or Decimal("0.40")
        return pay, "book"

    def both_ioc(_log, _key, spec, pay, step, send, other_price=None, other_fee=None):
        timeline.append(("ioc", step))
        payload = venue_fill_confirm.attach(
            {"status": "filled", "filledQuantity": "1"},
            {"known": True, "qty": "1.00", "note": "test"},
        )
        live_lock_orders._refresh_order_pages()
        live_lock_orders._after_send_hooks(spec, payload, 201)
        live_lock_orders._refresh_order_pages()
        timeline.append(("after_send", step))
        return {
            "filled": True,
            "payload": payload,
            "status": 201,
            "note": "filled",
            "pay": spec.get("pay"),
            "spec": spec,
            "step": step,
            "posted": True,
        }

    saved = _hard_first_harness(folder, kalshi, gemini, fake_book, both_ioc)
    saved_rewrite = live_lock_orders._rewrite_order_pages_now
    saved_sched = orders_performance_refresh.schedule_rebuild
    live_lock_orders._refresh_order_pages = saved[12]
    live_lock_orders._rewrite_order_pages_now = lambda: timeline.append("pages")
    orders_performance_refresh.schedule_rebuild = lambda reason: scheduled.append(reason) or True
    try:
        live_lock_orders._send_pair(lambda *_a, **_k: None, "k", "Game", [kalshi, gemini])
        assert timeline == [
            ("ioc", "hard"),
            ("after_send", "hard"),
            ("ioc", "easy"),
            ("after_send", "easy"),
            "pages",
        ]
        assert scheduled == ["fill", "fill"]
        assert live_lock_orders._send_html_hold == 0
        assert live_lock_orders._send_html_pending is False
        assert live_lock_orders._send_perf_pending == []
    finally:
        live_lock_orders._rewrite_order_pages_now = saved_rewrite
        orders_performance_refresh.schedule_rebuild = saved_sched
        live_lock_orders._send_html_hold = 0
        live_lock_orders._send_html_pending = False
        live_lock_orders._send_perf_pending.clear()
        _restore_hard_first(saved)


def test_standalone_send_still_rebuilds_pages_immediately():
    """Hold is pair-only. A lone _send still rewrites on request and on result."""
    pages = []
    live_lock_orders._hold_send_html()
    live_lock_orders._release_send_html()
    saved = live_lock_orders._rewrite_order_pages_now
    live_lock_orders._rewrite_order_pages_now = lambda: pages.append("pages")
    try:
        assert live_lock_orders._send_html_hold == 0
        live_lock_orders._refresh_order_pages()
        assert pages == ["pages"]
    finally:
        live_lock_orders._rewrite_order_pages_now = saved
        live_lock_orders._send_html_hold = 0
        live_lock_orders._send_html_pending = False
        live_lock_orders._send_perf_pending.clear()


def test_kalshi_market_payload_has_dollar_volume_fields():
    payload = {
        "market": {
            "ticker": "KXATPMATCH-26OCT25BERETC-BER",
            "volume_fp": "260.05",
            "volume_24h_fp": "236.76",
            "open_interest_fp": "259.71",
            "yes_ask_size_fp": "13258.00",
        }
    }
    got = live_lock_orders._market_size_from_payload("kalshi", payload)
    assert got["volume_fp"] == "260.05"
    assert got["volume_24h_fp"] == "236.76"
    assert got["open_interest_fp"] == "259.71"
    assert "yes_ask_size_fp" not in got


def test_poly_us_market_payload_without_volume_is_empty():
    payload = {
        "slug": "aec-atp-matber-tometc-2026-10-25",
        "bestBid": "0.61",
        "bestAsk": "0.63",
        "yes_ask": "0.63",
    }
    assert live_lock_orders._market_size_from_payload("polymarket", payload) == {}


def test_sent_row_logs_ask_size_and_kalshi_volume():
    spec = {
        "venue": "kalshi",
        "instrument": "KXATPMATCH-26OCT25BERETC-BER",
        "outcome": "yes",
        "pay": "0.63",
        "limit": "0.63",
        "_bet_key": "beretc",
        "quote_size": "29.10",
        "volume_fp": "260.05",
        "volume_24h_fp": "236.76",
        "open_interest_fp": "259.71",
    }
    live_lock_orders._attach_market_size(spec)
    row = live_lock_orders._sent_row(spec, "pending", None, "request sent")
    assert row["ask_size"] == "29.10"
    assert row["volume_fp"] == "260.05"
    assert row["volume_24h_fp"] == "236.76"
    assert row["open_interest_fp"] == "259.71"
    assert row["venue"] == "kalshi"
    assert row["instrument"] == "KXATPMATCH-26OCT25BERETC-BER"


def test_skip_row_logs_venue_ticker_ask_size():
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    saved = (live_lock_orders.ORDERS, live_lock_orders.LAST_SKIP, live_lock_orders._refresh_order_pages)
    live_lock_orders.ORDERS = folder / "orders.jsonl"
    live_lock_orders.LAST_SKIP = folder / "lock_last_skip.json"
    live_lock_orders._refresh_order_pages = lambda: None
    spec = {
        "venue": "polymarket",
        "instrument": "aec-atp-matber-tometc-2026-10-25",
        "quote_size": "0.19",
        "game": "Berrettini vs Etcheverry",
        "_bet_key": "beretc",
    }
    try:
        live_lock_orders.record_send_skip("poly_size_lt_qty_skip need>=1 saw=0.19", "Berrettini vs Etcheverry", "beretc", spec=spec)
        rows = [
            json.loads(line)
            for line in live_lock_orders.ORDERS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    finally:
        live_lock_orders.ORDERS = saved[0]
        live_lock_orders.LAST_SKIP = saved[1]
        live_lock_orders._refresh_order_pages = saved[2]
    assert rows
    skip = rows[-1]
    assert skip["event"] == "skip"
    assert skip["venue"] == "polymarket"
    assert skip["instrument"] == "aec-atp-matber-tometc-2026-10-25"
    assert skip["ask_size"] == "0.19"


def test_confirmed_fill_debits_local_cash():
    import venue_fill_confirm

    saved = _pin_balances("10")
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "yes",
        "pay": "0.40",
        "limit": "0.40",
        "fee_coefficient": None,
        "intent": "",
    }
    payload = venue_fill_confirm.attach(
        {"order_id": "k-fill-1", "fill_count": "1", "yes_price_dollars": "0.40"},
        {
            "known": True,
            "qty": "1",
            "avg_price": "0.40",
            "house_fill": True,
            "note": "qty 1",
            "order_id": "k-fill-1",
        },
    )
    try:
        live_lock_orders._apply_confirmed_fill_to_local_cash(spec, payload)
        kfee = live_lock_orders.kalshi_fee_amount(Decimal("0.40"))
        assert live_lock_orders._venue_balances["kalshi"] == Decimal("10") - Decimal("0.40") - kfee
    finally:
        _unpin_balances(saved)


def test_empty_kalshi_201_does_not_debit_local_cash():
    saved = _pin_balances("10")
    spec = {
        "venue": "kalshi",
        "instrument": "KX-TEST",
        "outcome": "yes",
        "pay": "0.40",
        "limit": "0.40",
        "fee_coefficient": None,
        "intent": "",
    }
    payload = {
        "order_id": "k-empty-1",
        "fill_count": "0",
        "_venue_confirm": {"known": True, "qty": "0", "note": "fill_count 0", "order_id": "k-empty-1"},
    }
    try:
        live_lock_orders._apply_confirmed_fill_to_local_cash(spec, payload)
        assert live_lock_orders._venue_balances["kalshi"] == Decimal("10")
    finally:
        _unpin_balances(saved)


def test_fee_returned_reads_average_fee_paid_not_zero():
    payload = {
        "average_fill_price": "0.4900",
        "average_fee_paid": "0.0175",
        "fill_count": "1.00",
        "fee": "0",
    }
    assert live_lock_orders.fee_returned(payload) == Decimal("0.0175")
    assert live_lock_orders.fee_returned({"fee": "0", "fill_count": "1"}) is None
    assert live_lock_orders.kalshi_fee_amount(Decimal("0.49"), payload) == Decimal("0.0175")
    estimate = live_lock_orders.kalshi_fee_amount(Decimal("0.49"))
    assert estimate == Decimal("0.0175")
    spec = {"venue": "kalshi", "fee_coefficient": None}
    assert live_lock_orders.leg_fee(spec, Decimal("0.49")) == Decimal("0.0175")
    assert live_lock_orders.leg_fee(spec, Decimal("0.49"), payload) == Decimal("0.0175")
    assert live_lock_orders.contract_cost(spec, "0.49") == Decimal("0.5075")


def test_bobichon_pair_net_and_sent_row_after_fee():
    cand = _pair(
        yes_venue="kalshi",
        no_venue="kalshi",
        yes_price="0.49",
        no_price="0.49",
    )
    net = live_lock_orders.pair_net(Scan(), cand)
    kfee = live_lock_orders.kalshi_fee_amount(Decimal("0.49"))
    assert kfee == Decimal("0.0175")
    assert net == Decimal("0.49") + Decimal("0.49") + kfee + kfee
    spec = {
        "venue": "kalshi",
        "instrument": "KX-BOB",
        "outcome": "yes",
        "pay": "0.49",
        "limit": "0.60",
        "_bet_key": "bobichon",
        "fee_coefficient": None,
        "intent": "",
    }
    pending = live_lock_orders._sent_row(spec, "pending", None, "request sent")
    assert pending["wire"] == "0.49"
    assert pending["fee"] == "0.0175"
    assert pending["after_fee"] == "0.5075"
    assert pending["fee_source"] == "estimate"
    payload = venue_fill_confirm.attach(
        {
            "order_id": "01a1745d-0680-77c7-820c-bf77357ab3df",
            "average_fill_price": "0.4900",
            "average_fee_paid": "0.0175",
            "fill_count": "1.00",
        },
        {"known": True, "qty": "1", "avg_price": "0.49", "house_fill": True, "note": "qty 1"},
    )
    filled = live_lock_orders._sent_row(spec, 201, payload, "filled")
    assert filled["wire"] == "0.49"
    assert filled["fee"] == "0.0175"
    assert filled["after_fee"] == "0.5075"
    assert filled["fee_source"] == "venue"
    empty = live_lock_orders._sent_row(
        spec, 201, {"fill_count": "0", "_venue_confirm": {"known": True, "qty": "0"}}, "empty",
    )
    assert empty["fee_source"] == "no_fill"
    assert empty["after_fee"] == ""
    assert empty["fee"] == ""


def test_confirmed_fill_debits_average_fee_paid_not_wire():
    saved = _pin_balances("10")
    spec = {
        "venue": "kalshi",
        "instrument": "KX-BOB",
        "outcome": "yes",
        "pay": "0.49",
        "limit": "0.60",
        "fee_coefficient": None,
        "intent": "",
    }
    payload = venue_fill_confirm.attach(
        {
            "order_id": "k-bob-1",
            "fill_count": "1",
            "average_fill_price": "0.49",
            "average_fee_paid": "0.0175",
        },
        {"known": True, "qty": "1", "avg_price": "0.49", "house_fill": True, "order_id": "k-bob-1"},
    )
    try:
        live_lock_orders._apply_confirmed_fill_to_local_cash(spec, payload)
        assert live_lock_orders._venue_balances["kalshi"] == Decimal("9.4925")
    finally:
        _unpin_balances(saved)


def test_kalshi_no_confirm_avg_is_house_cash_not_yes_wire():
    """Osborne: fills GET No 0.89. Do not invert again to a 0.11 debit."""
    spec = {
        "venue": "kalshi",
        "instrument": "KXWTACHALLENGERMATCH-26OCT25OSBHIN-OSB",
        "outcome": "no",
        "pay": "0.93",
        "limit": "0.07",
        "fee_coefficient": None,
        "intent": "",
    }
    payload = venue_fill_confirm.attach(
        {
            "order_id": "01a179a7-e628-7aef-9600-afe97ae29d38",
            "fill_count": "1.00",
            "average_fill_price": "0.1100",
            "average_fee_paid": "0.0069",
        },
        {
            "known": True,
            "qty": "1.00",
            "avg_price": "0.8900",
            "house_fill": True,
            "note": "kalshi fills GET qty 1.00 @ 0.8900",
            "order_id": "01a179a7-e628-7aef-9600-afe97ae29d38",
        },
    )
    assert live_lock_orders._actual_fill_cash(spec, payload) == Decimal("0.8900")
    saved = _pin_balances("10")
    try:
        live_lock_orders._apply_confirmed_fill_to_local_cash(spec, payload)
        assert live_lock_orders._venue_balances["kalshi"] == Decimal("9.1031")
    finally:
        _unpin_balances(saved)
    tape = {
        "order_id": "01a179a7-e628-7aef-9600-afe97ae29d38",
        "fill_count": "1.00",
        "average_fill_price": "0.1100",
        "average_fee_paid": "0.0069",
        "no_price_dollars": "0.8900",
        "yes_price_dollars": "0.1100",
    }
    assert live_lock_orders._actual_fill_cash(spec, tape) == Decimal("0.8900")
    yes_wire_only = {
        "order_id": "01a179a7-e628-7aef-9600-afe97ae29d38",
        "fill_count": "1.00",
        "average_fill_price": "0.1100",
        "average_fee_paid": "0.0069",
    }
    assert live_lock_orders._actual_fill_cash(spec, yes_wire_only) == Decimal("0.8900")


def test_osborne_fill_pair_net_denies_vs_099():
    """Kalshi No 89¢ + 0.69¢ + Poly Yes 12¢ + 1¢ = 1.0269. Must not send."""
    old = live_lock_orders.NET_MAX
    try:
        live_lock_orders.NET_MAX = Decimal("0.99")
        cand = _pair(
            market_type="moneyline",
            side="Alexandra Osborne",
            number="",
            yes_venue="polymarket",
            no_venue="kalshi",
            yes_price="0.12",
            no_price="0.89",
            polymarket_fee="0.01",
            kalshi_ticker="KXWTACHALLENGERMATCH-26OCT25OSBHIN-OSB",
            polymarket_slug="aec-wta-aleosb-jeshin-2026-10-25",
            polymarket_intent="ORDER_INTENT_BUY_LONG",
        )
        net = live_lock_orders.pair_net(Scan(), cand)
        kfee = live_lock_orders.kalshi_fee_amount(Decimal("0.89"))
        assert kfee == Decimal("0.0069")
        assert net == Decimal("0.89") + Decimal("0.12") + kfee + Decimal("0.01")
        assert net == Decimal("1.0269")
        assert net > live_lock_orders.effective_net_max()
        ok, reason = live_lock_orders.qualifies(Scan(), cand, "Osborne vs Hinojosa Gomez", {})
        assert not ok
        assert "1.0269" in reason
        cheap = dict(cand, no_price="0.07")
        cheap_net = live_lock_orders.pair_net(Scan(), cheap)
        assert cheap_net is not None and cheap_net < Decimal("0.99")
        blocked = live_lock_orders._profit_block(
            {"venue": "kalshi", "fee_coefficient": None},
            Decimal("0.14"),
            Decimal("0.89"),
            kfee,
        )
        assert blocked.startswith("limit=")
    finally:
        live_lock_orders.NET_MAX = old


def test_kalshi_no_funds_use_house_pay_not_yes_wire_limit():
    """Osborne POST ask 7¢ is Yes-wire. Cash / funds must use No 89¢ once."""
    spec = live_lock_orders._leg_spec(
        {
            "yes_venue": "polymarket",
            "no_venue": "kalshi",
            "yes_price": "0.12",
            "no_price": "0.89",
            "kalshi_ticker": "KXWTACHALLENGERMATCH-26OCT25OSBHIN-OSB",
            "polymarket_slug": "aec-wta-aleosb-jeshin-2026-10-25",
            "polymarket_intent": "ORDER_INTENT_BUY_LONG",
        },
        "no",
    )
    assert spec is not None
    assert spec["pay"] == "0.89"
    assert spec["limit"] == "0.1100"
    cash = live_lock_orders._leg_cash_price(spec)
    assert cash == Decimal("0.89")
    fee = live_lock_orders.kalshi_fee_amount(Decimal("0.89"))
    assert live_lock_orders.contract_cost(spec, cash) == Decimal("0.89") + fee
    assert live_lock_orders.leg_fee(spec, cash) == fee
    wire_only = {"venue": "kalshi", "outcome": "no", "limit": "0.07", "fee_coefficient": None}
    assert live_lock_orders._leg_cash_price(wire_only) == Decimal("0.93")
    both = {"venue": "kalshi", "outcome": "no", "pay": "0.89", "limit": "0.07", "fee_coefficient": None}
    assert live_lock_orders._leg_cash_price(both) == Decimal("0.89")
    saved = _pin_balances("0.20")
    try:
        assert live_lock_orders._affordable(spec, live_lock_orders._venue_balances) is False
        note = live_lock_orders._funds_block(spec)
        assert "cost=" in note
        assert "0.07" not in note.split("cost=", 1)[-1].split()[0]
    finally:
        _unpin_balances(saved)


def test_novig_pair_net_uses_documented_fee_not_unknown():
    live = _pair(
        yes_venue="novig",
        no_venue="kalshi",
        yes_price="0.38",
        no_price="0.5729",
        fee_coefficient="0.06",
        fee_charged="WHEN_LIVE",
        event_status="OPEN_INGAME",
    )
    net = live_lock_orders.pair_net(Scan(), live)
    novig_fee = Decimal("0.01414")
    kfee = live_lock_orders.kalshi_fee_amount(Decimal("0.5729"))
    assert net == Decimal("0.38") + Decimal("0.5729") + novig_fee + kfee
    pregame = dict(live, event_status="OPEN_PREGAME")
    pre = live_lock_orders.pair_net(Scan(), pregame)
    assert pre == Decimal("0.38") + Decimal("0.5729") + Decimal("0") + kfee
    missing = dict(live, fee_coefficient=None)
    assert live_lock_orders.pair_net(Scan(), missing) is None
    spec = {
        "venue": "novig",
        "fee_coefficient": "0.06",
        "fee_charged": "WHEN_LIVE",
        "event_status": "OPEN_INGAME",
    }
    assert live_lock_orders.leg_fee(spec, Decimal("0.38")) == novig_fee


if __name__ == "__main__":
    test_net_at_095_qualifies()
    test_net_above_095_stays_alert_only()
    test_hair_over_net_max_skip_shows_unrounded_cost()
    test_net_max_full_precision_accepts_0983_rejects_105()
    test_opportunity_skip_reason_uses_live_net_max()
    test_leg_deny_reason_names_missing_fields()
    test_display_rewrites_old_missing_order_fields()
    test_catalog_eligible_reason_is_not_a_send_deny()
    test_record_catalog_logs_eligible_quote_as_catalog_only()
    test_fmt_after_fee_cost_is_at_least_four_decimals()
    test_qualifies_compares_unrounded_decimal_not_round2()
    test_cap_099_sends_0986_denies_0991()
    test_opportunities_row_display_is_four_decimals()
    test_catalog_recomputes_rounded_net_before_send_compare()
    test_catalog_verify_second_row_still_gap()
    test_catalog_verify_second_row_gap_closed()
    test_catalog_verify_429_named_no_retry()
    test_catalog_verify_missing_fields_named()
    test_catalog_verify_never_posts_orders()
    test_catalog_verify_recheck_is_parallel()
    test_catalog_verify_hands_books_to_execute_when_still_gap()
    test_catalog_verify_does_not_execute_when_gap_closed()
    test_recheck_pair_books_is_parallel_and_skips_pace()
    test_recheck_over_cap_reason_names_both_rest_sizes()
    test_send_pair_skip_book_recheck_does_not_fetch()
    test_send_line_copy_follows_net_max()
    test_unrounded_cost_under_send_line_is_not_printed_as_above()
    test_execute_locks_sends_when_unrounded_cost_is_under_send_line()
    test_size_cap_needs_one_whole_contract()
    test_tennessee_13_5_is_blocked()
    test_flipped_gemini_no_is_blocked()
    test_missing_moves_send_kalshi_first()
    test_kalshi_no_is_a_yes_ask_at_one_minus_price()
    test_polymarket_short_price_does_not_pay_more()
    test_open_lock_keys_counts_live_true_locks_not_flatten_or_history()
    test_open_lock_keys_ignores_dead_claims_and_unfilled_sends()
    test_execute_locks_skips_when_open_lock_cap_hit()
    test_house_three_open_venues_zero_allows_send()
    test_execute_locks_denies_tbcar_nms_mix()
    test_bind_consider_drops_stale_tbcar_nms()
    test_tape_filled_qty_ignores_book_qtydecimal()
    test_open_lock_keys_unique_games_venue_qty()
    test_open_lock_keys_drops_claims_empty_201_flattened_settled()
    test_filled_and_blocked()
    test_one_leg_message_is_separate_from_the_under_1_ping()
    test_one_leg_message_reads_gemini_avg_execution_price()
    test_send_returns_before_order_http_when_off()
    test_carolina_cap_allows_081_and_blocks_082()
    test_ioc_cancel_includes_the_gemini_email_case()
    test_websocket_read_times_out_when_the_price_never_arrives()
    test_leg_tries_websocket_then_book_then_midway_and_stops()
    test_timeout_uses_the_book_and_skips_a_midway_above_the_max()
    test_calgary_book_ask_over_a_dollar_is_not_posted()
    test_over_cap_quote_is_skipped_and_a_later_under_cap_try_is_sent()
    test_over_cap_book_can_still_send_a_midway_price_under_the_cap()
    test_kalshi_leg_is_not_sent_when_the_gemini_fill_is_no_longer_profitable()
    test_short_or_unread_balance_is_not_sent()
    test_balance_deny_reason_names_venue_and_low_vs_unread()
    test_kalshi_probe_429_uses_last_good()
    test_unread_skip_rate_limit_does_not_append_every_tick()
    test_stale_zero_balance_is_refetched()
    test_failed_balance_read_keeps_last_good()
    test_simultaneous_legs_and_only_a_one_leg_latches()
    test_one_sided_fill_stops_for_any_venue()
    test_gemini_book_ask_reads_the_websocket_fields()
    test_order_io_redacts_secret_keys_and_keeps_reason()
    test_shard_user_404_retries_the_same_limit_twice_more()
    test_shard_user_404_stops_when_a_later_post_is_accepted()
    test_ordinary_reject_and_ioc_cancel_are_not_retried()
    test_one_ioc_keeps_partial_fill_qty_after_cancel()
    test_shard_user_posts_are_each_logged_in_order_io()
    test_send_schedules_performance_on_confirmed_fill_not_on_deny()
    test_send_rebuilds_pages_on_request_and_on_result()
    test_send_returns_kalshi_fill_when_ledger_replace_fails()
    test_pending_kalshi_row_uses_order_io_fill_count()
    test_result_replaces_pending_order_row()
    test_gemini_order_fields_match_the_rest_shape()
    test_poly_order_body_is_fok_kalshi_gemini_novig_still_ioc()
    test_poly_size_019_skip_does_not_post()
    test_poly_size_ge_1_fok_fill_1_is_house_open()
    test_guajardo_002_book_skips_poly()
    test_spot_order_path_is_refused()
    test_pick_trigger_uses_the_newest_nonzero_move()
    test_sent_row_and_order_io_keep_trigger_quotes()
    test_watch_ioc_sends_while_latch_on_and_fill_turns_orders_back_on()
    test_leftover_watch_loop_has_no_datetime_cutoff()
    test_leftover_after_friday_8am_still_eligible()
    test_watch_tick_errors_do_not_raise()
    test_reconstruct_watch_from_mtu_one_leg()
    test_watch_sequential_cheapest_stops_after_first_fill()
    test_watch_send_once_stops_after_miss()
    test_watch_partial_fill_does_not_retry()
    test_origin_404_keeps_watching_other_venues()
    test_persist_keeps_two_settlement_watches()
    test_send_kalshi_fill_registers_watch_when_ledger_fails()
    test_do_not_leftover_watch_a_directional_dog()
    test_lock_a_persist_still_opens_leftover_e_does_not()
    test_e_leftover_watch_does_not_send_55c_favorite()
    test_onclin_hedge_skips_struff_no()
    test_watch_already_both_ignores_same_bet_no()
    test_send_gate_skips_empty_other_book()
    test_kalshi_201_fill_count_zero_is_not_a_fill()
    test_weak_filled_flag_without_qty_is_not_a_fill()
    test_status_filled_without_qty_is_not_a_fill()
    test_send_pair_does_not_log_both_filled_on_empty_201()
    test_send_pair_status_filled_without_qty_is_both_unfilled()
    test_record_sent_same_second_does_not_stack_quote_patches()
    test_public_note_kalshi_201_fill_count_zero_is_cancel_text()
    test_opportunities_page_shows_venue_return_on_sent_row()
    test_ghost_overlay_strikes_mixed_tbcar_nms_sent()
    test_pick_hard_leg_smaller_size_then_venue_then_price()
    test_hard_miss_does_not_send_easy()
    test_hard_fill_gap_closed_flattens_not_second_send()
    test_hard_fill_gap_open_sends_easy()
    test_send_pair_defers_html_until_after_both_ioc()
    test_standalone_send_still_rebuilds_pages_immediately()
    test_kalshi_market_payload_has_dollar_volume_fields()
    test_poly_us_market_payload_without_volume_is_empty()
    test_sent_row_logs_ask_size_and_kalshi_volume()
    test_skip_row_logs_venue_ticker_ask_size()
    test_confirmed_fill_debits_local_cash()
    test_empty_kalshi_201_does_not_debit_local_cash()
    test_fee_returned_reads_average_fee_paid_not_zero()
    test_bobichon_pair_net_and_sent_row_after_fee()
    test_confirmed_fill_debits_average_fee_paid_not_wire()
    test_kalshi_no_confirm_avg_is_house_cash_not_yes_wire()
    test_osborne_fill_pair_net_denies_vs_099()
    test_kalshi_no_funds_use_house_pay_not_yes_wire_limit()
    test_novig_pair_net_uses_documented_fee_not_unknown()
    print("ok")
