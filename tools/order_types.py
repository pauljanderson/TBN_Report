"""Per-order type labels for live systems A–G. Display only. Does not send."""
from __future__ import annotations

from decimal import Decimal

TYPE_A_LOW = "initial lock low size side"
TYPE_A_HIGH = "final lock hi size side"
TYPE_A_FLAT = "flatten (close initial lock)"
TYPE_B_HI = "initial Hi lock"
TYPE_B_LO = "initial low lock"
TYPE_B_CROSS = "crossover lock"
TYPE_B_SUB = "subsequent low lock"
TYPE_C = "only lock 0.50 - 0.90"
TYPE_D = "only lock 0.50 - 0.90"
TYPE_E = "only lock underdog T0"
TYPE_F = "only lock tennis spread T0"
TYPE_G = "G Soccer total"
TYPE_LEFTOVER = "leftover / hedge"

LABELS = (
    TYPE_A_LOW,
    TYPE_A_HIGH,
    TYPE_A_FLAT,
    TYPE_B_HI,
    TYPE_B_LO,
    TYPE_B_CROSS,
    TYPE_B_SUB,
    TYPE_C,
    TYPE_D,
    TYPE_E,
    TYPE_F,
    TYPE_G,
    TYPE_LEFTOVER,
)
LABEL_SET = set(LABELS)

SYSTEM_LETTER = {
    "lock": "A",
    "a": "A",
    "tennis_crossover": "B",
    "b": "B",
    "cfb_favorite": "C",
    "c": "C",
    "spread_t0": "D",
    "d": "D",
    "tennis_t0_dog": "E",
    "e": "E",
    "tennis_t0_spread": "F",
    "f": "F",
    "soccer_t0_total": "G",
    "g": "G",
}

_A_FLAT = {"flatten", "extra-flatten"}
_A_LOW = {"hard"}
_A_HIGH = {"easy", "watch", "recovery"}
_B_T0 = {"b-t0", "t0"}
_B_CROSS = {"b-cross"}
_B_SUB = {"b-leftover-yes", "b-fav"}
_LEFTOVER_STEPS = {"watch", "recovery"}
_DIRECTIONAL_LETTERS = {"C", "D", "E", "F", "G"}
HALF = Decimal("0.50")


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def letter_of(system_id: str | None, *, cluster_letter: str | None = None) -> str:
    if cluster_letter and str(cluster_letter).upper() in {"A", "B", "C", "D", "E", "F", "G"}:
        return str(cluster_letter).upper()
    key = str(system_id or "").strip().lower().replace(" ", "_").replace("-", "_")
    return SYSTEM_LETTER.get(key, "")


def cluster_letter(cluster: dict | None) -> str:
    cluster = cluster or {}
    letter = str(cluster.get("system_letter") or "").upper()
    if letter in {"A", "B", "C", "D", "E", "F", "G"}:
        return letter
    kind = str(cluster.get("kind") or "").strip().lower().replace("-", "_")
    return SYSTEM_LETTER.get(kind, letter_of(str(cluster.get("system") or cluster.get("system_id") or "")))


def is_directional_leftover(leg: dict | None, cluster: dict | None = None) -> bool:
    """Lock leftover-watch hedge sitting on a C/D/E bet_key. Not an E dog send."""
    step = str((leg or {}).get("step") or "").strip().lower()
    if step not in _LEFTOVER_STEPS:
        return False
    return cluster_letter(cluster) in _DIRECTIONAL_LETTERS


def classify(
    *,
    letter: str,
    step: str = "",
    cash=None,
    limit=None,
    ask_size=None,
    sibling_t0_prices: list | None = None,
    sibling_sizes: list | None = None,
) -> str:
    """One send → one type. Uses the frozen A–E roles Paul named."""
    letter = str(letter or "").upper()
    step = str(step or "").strip().lower()
    if step in _LEFTOVER_STEPS and letter in _DIRECTIONAL_LETTERS:
        return TYPE_LEFTOVER
    if letter == "C":
        return TYPE_C
    if letter == "D":
        return TYPE_D
    if letter == "E":
        return TYPE_E
    if letter == "F":
        return TYPE_F
    if letter == "G":
        return TYPE_G
    if letter == "A":
        return _type_a(step, ask_size, sibling_sizes)
    if letter == "B":
        if step in _A_FLAT:
            return TYPE_A_FLAT
        return _type_b(step, cash, limit, sibling_t0_prices)
    return ""


def _type_a(step: str, ask_size, sibling_sizes) -> str:
    if step in _A_FLAT:
        return TYPE_A_FLAT
    if step in _A_LOW:
        return TYPE_A_LOW
    if step in _A_HIGH:
        return TYPE_A_HIGH
    size = _dec(ask_size)
    sizes = [_dec(item) for item in (sibling_sizes or [])]
    sizes = [item for item in sizes if item is not None]
    if size is not None and len(sizes) >= 2:
        lo, hi = min(sizes), max(sizes)
        if lo != hi:
            return TYPE_A_LOW if size <= lo else TYPE_A_HIGH
    return TYPE_A_LOW


def _type_b(step: str, cash, limit, sibling_t0_prices) -> str:
    if step in _B_CROSS:
        return TYPE_B_CROSS
    if step in _B_SUB:
        return TYPE_B_SUB
    price = _dec(cash)
    if price is None:
        price = _dec(limit)
    prices = [_dec(item) for item in (sibling_t0_prices or [])]
    prices = [item for item in prices if item is not None]
    if price is not None and len(prices) >= 2:
        hi, lo = max(prices), min(prices)
        if hi != lo:
            return TYPE_B_HI if price >= hi else TYPE_B_LO
    if price is not None:
        return TYPE_B_HI if price >= HALF else TYPE_B_LO
    if step in _B_T0 or not step:
        return TYPE_B_LO
    return TYPE_B_SUB


def _b_t0_price(row: dict | None):
    """House Yes cash for B T0 hi/low. Quote/yes_ask, not Poly BUY_SHORT Yes-wire."""
    row = row or {}
    return (
        row.get("quote_price")
        or row.get("yes_ask")
        or row.get("cash")
        or row.get("wire")
        or row.get("limit_price")
        or row.get("limit")
    )


def from_sent(sent: dict | None, siblings: list | None, system_id: str, *, letter: str = "") -> str:
    sent = sent or {}
    sibs = [row for row in (siblings or []) if isinstance(row, dict)]
    step = str(sent.get("step") or "")
    t0_prices = []
    sizes = []
    for other in sibs or [sent]:
        ost = str(other.get("step") or "")
        if ost in _B_T0 or (not ost and other is sent):
            t0_prices.append(_b_t0_price(other))
        if ost not in _A_FLAT:
            sizes.append(other.get("ask_size") or other.get("quote_size"))
    return classify(
        letter=letter_of(system_id, cluster_letter=letter),
        step=step,
        cash=_b_t0_price(sent) if step in _B_T0 else (sent.get("cash") or sent.get("wire")),
        limit=sent.get("limit_price") or sent.get("limit"),
        ask_size=sent.get("ask_size") or sent.get("quote_size"),
        sibling_t0_prices=t0_prices,
        sibling_sizes=sizes,
    )


def from_leg(leg: dict | None, cluster: dict | None) -> str:
    leg = leg or {}
    cluster = cluster or {}
    letter = cluster_letter(cluster)
    step = str(leg.get("step") or "")
    t0_prices = []
    sizes = []
    for other in cluster.get("legs") or cluster.get("fill_legs") or []:
        if not isinstance(other, dict):
            continue
        ost = str(other.get("step") or "")
        if ost in _B_T0:
            t0_prices.append(_b_t0_price(other))
        if ost not in _A_FLAT:
            sizes.append(other.get("ask_size") or other.get("quote_size"))
    return classify(
        letter=letter_of("", cluster_letter=letter),
        step=step,
        cash=_b_t0_price(leg) if step in _B_T0 else leg.get("cash"),
        limit=leg.get("limit"),
        ask_size=leg.get("ask_size") or leg.get("quote_size"),
        sibling_t0_prices=t0_prices,
        sibling_sizes=sizes,
    )


def open_now_type(
    letter: str,
    *,
    step: str = "",
    cross_fill: str = "",
    stage: str = "",
) -> str:
    """Compact Type for Open now / Positions. Same family as orders tables."""
    letter = str(letter or "").upper()
    step = str(step or "").strip().lower()
    stage = str(stage or "").strip().lower()
    if letter == "A":
        return "A lock gap"
    if letter == "C":
        return "C CFB favorite"
    if letter == "D":
        return "D T0 spreads"
    if letter == "E":
        return "E dog"
    if letter == "F":
        return "F Tennis spread"
    if letter == "G":
        return "G Soccer total"
    if letter == "B":
        if step in _B_CROSS or (str(cross_fill or "").strip() and stage in {"waiting_fav_dip", "fav_gtc_resting", "absorbed"}):
            return "B crossover"
        if step in _B_SUB:
            return "B subsequent"
        return "B T0"
    return letter or "—"


def cluster_types(cluster: dict | None) -> str:
    seen: list[str] = []
    cluster = cluster or {}
    for leg in cluster.get("legs") or cluster.get("fill_legs") or []:
        label = from_leg(leg, cluster)
        if label and label not in seen:
            seen.append(label)
    return " / ".join(seen)
