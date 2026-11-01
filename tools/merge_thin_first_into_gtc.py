#!/usr/bin/env python3
"""Merge trading-PC thin-first pieces into clean GTC live_lock_orders.py.

Paul's thin-first (_pick_hard_leg / flatten_filled_leg / hard-first send order)
lives only on the trading PC. After a conflicted pull, the backup at
tools/_merge_backup/live_lock_orders.py holds the local side (possibly still
with git conflict markers). This helper:

  1. De-conflicts the backup (prefer OURS for thin-first symbols, THEIRS for GTC)
  2. Extracts thin-first defs / constants / call sites from that text
  3. Injects them into the current clean GTC tools/live_lock_orders.py
  4. Patches the execute_locks send-order line to call _pick_hard_leg when present
  5. Refuses loudly if thin-first cannot be found (never invents trading semantics)

Usage (from repo root):
  python tools/merge_thin_first_into_gtc.py
  python tools/merge_thin_first_into_gtc.py --dry-run
  python tools/merge_thin_first_into_gtc.py --self-test
  python tools/merge_thin_first_into_gtc.py --backup PATH --gtc PATH --out PATH
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP = ROOT / "tools" / "_merge_backup" / "live_lock_orders.py"
DEFAULT_GTC = ROOT / "tools" / "live_lock_orders.py"
DEFAULT_OUT = DEFAULT_GTC
BEFORE_BACKUP = ROOT / "tools" / "_merge_backup" / "live_lock_orders.before_thin_merge.py"

THIN_SYMBOLS = (
    "_pick_hard_leg",
    "flatten_filled_leg",
    "VENUE_MISS_RANK",
    "hard_miss_abort",
    "thin_first",
    "quote_size",
    "_hard_leg",
    "HARD_MISS",
)
GTC_SYMBOLS = (
    "_with_tif",
    "ONE_LEG_GTC_WAIT_SEC",
    "CHEAP_EXIT_MAX",
    "tick_one_leg_gtc_watches",
    "cancel_second_leg_gtc_on_resolve",
    "orders_enabled",
    "synchronousExecution",
    "BE_COMPLETE_SLIP",
    "second_leg_gtc",
)

# Top-level names we try to lift from backup into GTC when missing.
EXTRACT_DEFS = (
    "_pick_hard_leg",
    "flatten_filled_leg",
    "_hard_leg_key",
    "_hard_leg_size",
    "_venue_miss_rank",
    "_quote_size_for_leg",
    "_leg_quote_size",
    "_thin_first_outcomes",
    "hard_first_outcomes",
)
EXTRACT_ASSIGNS = (
    "VENUE_MISS_RANK",
    "THIN_FIRST",
    "HARD_FIRST",
)

CONFLICT_START = re.compile(r"^<<<<<<< .*$")
CONFLICT_MID = re.compile(r"^=======\s*$")
CONFLICT_END = re.compile(r"^>>>>>>> .*$")

# Allow trailing comments — trading-PC lines often end with "# thin-first".
ORDERED_CALL_RE = re.compile(
    r"^([ \t]*)outcomes\s*=\s*ordered_outcomes\(([^)]*)\)\s*(?:#.*)?$",
    re.M,
)
PICK_CALL_RE = re.compile(
    r"^([ \t]*)outcomes\s*=\s*_pick_hard_leg\(([^)]*)\)\s*(?:#.*)?$",
    re.M,
)
# Backup may call pick differently, e.g. hard, easy = _pick_hard_leg(...)
PICK_ANY_CALL_RE = re.compile(r"_pick_hard_leg\(([^)]*)\)")


class MergeError(RuntimeError):
    """Loud failure — do not silently invent thin-first."""


def _count_hits(text: str, symbols: tuple[str, ...]) -> int:
    return sum(text.count(sym) for sym in symbols)


def _match_is_def_signature(src: str, match: re.Match) -> bool:
    """True when `_pick_hard_leg(` is the function *definition*, not a call."""
    line_start = src.rfind("\n", 0, match.start()) + 1
    prefix = src[line_start : match.start()]
    return bool(re.search(r"(?m)^\s*def\s+$", prefix)) or prefix.lstrip().startswith(
        "def "
    )


def _bare_call_args(args: str) -> str:
    """Turn typed def params into call-safe names.

    `cand: dict, fresh: list[dict]` → `cand, fresh`
    `cand, fresh` → `cand, fresh`
    """
    args = (args or "").strip().rstrip(",")
    if not args:
        return ""
    if ":" not in args and "->" not in args:
        return args
    names: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in args:
        if ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == "," and depth == 0:
            part = "".join(cur).strip()
            cur = []
            if not part:
                continue
            name = part.split(":", 1)[0].strip().split("=", 1)[0].strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                names.append(name)
        else:
            cur.append(ch)
    part = "".join(cur).strip()
    if part:
        name = part.split(":", 1)[0].strip().split("=", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            names.append(name)
    return ", ".join(names)


def _extract_pick_call_args(backup_src: str) -> str | None:
    """Args for `outcomes = _pick_hard_leg(...)` — never a typed def signature.

    Prefer a real call site. If the only hit is `def _pick_hard_leg(cand: dict, ...)`,
    strip annotations to bare names (or return None so the patch uses GTC's
    ordered_outcomes args). Using typed params verbatim produces:
      outcomes = _pick_hard_leg(cand: dict, fresh: list[dict])  # SyntaxError
    which previously failed around the shifted execute_locks line (~1228).
    """
    pick_calls = list(PICK_CALL_RE.finditer(backup_src))
    if pick_calls:
        return _bare_call_args(pick_calls[0].group(2))

    for m in PICK_ANY_CALL_RE.finditer(backup_src):
        if _match_is_def_signature(backup_src, m):
            continue
        return _bare_call_args(m.group(1))

    # Only the def existed (call site still ordered_outcomes after conflict strip).
    for m in PICK_ANY_CALL_RE.finditer(backup_src):
        if _match_is_def_signature(backup_src, m):
            bare = _bare_call_args(m.group(1))
            return bare or None
    return None


def _syntax_error_context(src: str, exc: SyntaxError, radius: int = 5) -> str:
    """Render ±radius lines around a SyntaxError for the FAIL message."""
    lineno = exc.lineno or 0
    lines = src.splitlines()
    if not lineno or not lines:
        return f"{exc}"
    start = max(1, lineno - radius)
    end = min(len(lines), lineno + radius)
    out = [
        f"{exc} (line {lineno})",
        f"----- merged source lines {start}-{end} -----",
    ]
    for i in range(start, end + 1):
        mark = ">>" if i == lineno else "  "
        out.append(f"{mark} {i}: {lines[i - 1]}")
    out.append("-----")
    return "\n".join(out)


def strip_conflict_markers(text: str) -> tuple[str, int, list[str]]:
    """Resolve <<<<<<< / ======= / >>>>>>> hunks.

    Prefer OURS when the hunk mentions thin-first symbols more (or exclusively).
    Prefer THEIRS when the hunk mentions GTC symbols more.
    Ties / empty: prefer OURS (backup is the local trading-PC side).
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    notes: list[str] = []
    i = 0
    resolved = 0
    while i < len(lines):
        line = lines[i]
        if not CONFLICT_START.match(line.rstrip("\n")):
            out.append(line)
            i += 1
            continue
        ours: list[str] = []
        theirs: list[str] = []
        i += 1
        while i < len(lines) and not CONFLICT_MID.match(lines[i].rstrip("\n")):
            if CONFLICT_START.match(lines[i].rstrip("\n")) or CONFLICT_END.match(
                lines[i].rstrip("\n")
            ):
                raise MergeError(
                    "Malformed conflict markers in backup (nested/missing =======)."
                )
            ours.append(lines[i])
            i += 1
        if i >= len(lines) or not CONFLICT_MID.match(lines[i].rstrip("\n")):
            raise MergeError("Malformed conflict markers in backup (missing =======).")
        i += 1
        while i < len(lines) and not CONFLICT_END.match(lines[i].rstrip("\n")):
            theirs.append(lines[i])
            i += 1
        if i >= len(lines) or not CONFLICT_END.match(lines[i].rstrip("\n")):
            raise MergeError("Malformed conflict markers in backup (missing >>>>>>>).")
        i += 1
        ours_txt = "".join(ours)
        theirs_txt = "".join(theirs)
        thin_o = _count_hits(ours_txt, THIN_SYMBOLS)
        thin_t = _count_hits(theirs_txt, THIN_SYMBOLS)
        gtc_o = _count_hits(ours_txt, GTC_SYMBOLS)
        gtc_t = _count_hits(theirs_txt, GTC_SYMBOLS)
        if thin_o > thin_t and thin_o > 0:
            choice, label = ours, "ours(thin)"
        elif gtc_t > gtc_o and gtc_t > 0 and thin_t == 0:
            choice, label = theirs, "theirs(gtc)"
        elif thin_t > thin_o and thin_t > 0 and gtc_o == 0:
            # Unusual but possible if sides flipped
            choice, label = theirs, "theirs(thin)"
        elif gtc_o > gtc_t and gtc_o > 0 and thin_o == 0:
            choice, label = ours, "ours(gtc)"
        else:
            # Default: keep local (ours) — that is the thin-first PC side.
            choice, label = ours, "ours(default)"
        notes.append(
            f"conflict#{resolved + 1}: kept {label} "
            f"(thin ours={thin_o}/theirs={thin_t}, gtc ours={gtc_o}/theirs={gtc_t})"
        )
        out.extend(choice)
        resolved += 1
    return "".join(out), resolved, notes


def _top_level_spans(src: str) -> list[tuple[str, str, int, int, str]]:
    """Return (kind, name, start_line, end_line, text) for top-level defs/assigns.

    kind is 'def' or 'assign'. Lines are 1-indexed inclusive.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise MergeError(
            f"Backup (after conflict strip) is not valid Python: {exc}. "
            "Fix markers manually or paste a clean thin-first copy into "
            "tools/_merge_backup/live_lock_orders.py and re-run."
        ) from exc
    lines = src.splitlines(keepends=True)
    spans: list[tuple[str, str, int, int, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", None) or node.lineno
            text = "".join(lines[start - 1 : end])
            spans.append(("def", node.name, start, end, text))
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in EXTRACT_ASSIGNS:
                    start = node.lineno
                    end = getattr(node, "end_lineno", None) or node.lineno
                    text = "".join(lines[start - 1 : end])
                    spans.append(("assign", tgt.id, start, end, text))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in EXTRACT_ASSIGNS:
                start = node.lineno
                end = getattr(node, "end_lineno", None) or node.lineno
                text = "".join(lines[start - 1 : end])
                spans.append(("assign", node.target.id, start, end, text))
    return spans


def extract_thin_pieces(backup_src: str) -> dict:
    """Pull thin-first defs / constants / call args from de-conflicted backup."""
    if "_pick_hard_leg" not in backup_src:
        raise MergeError(
            "Backup has no _pick_hard_leg after conflict resolution.\n"
            "Expected tools/_merge_backup/live_lock_orders.py to be the conflicted\n"
            "or pre-pull trading-PC copy that still contains thin-first.\n"
            "Restore that file from your merge backup, then re-run."
        )
    spans = _top_level_spans(backup_src)
    by_name = {name: (kind, text) for kind, name, _s, _e, text in spans}
    pieces: dict[str, str] = {}
    missing_required = []
    if "_pick_hard_leg" not in by_name:
        missing_required.append("_pick_hard_leg")
    else:
        pieces["_pick_hard_leg"] = by_name["_pick_hard_leg"][1]
    for name in EXTRACT_DEFS:
        if name == "_pick_hard_leg":
            continue
        if name in by_name:
            pieces[name] = by_name[name][1]
    for name in EXTRACT_ASSIGNS:
        if name in by_name:
            pieces[name] = by_name[name][1]

    # Also grab any top-level helper defs that _pick_hard_leg references and GTC lacks.
    pick_body = pieces.get("_pick_hard_leg", "")
    helper_names = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", pick_body))
    for kind, name, _s, _e, text in spans:
        if kind != "def":
            continue
        if name in pieces:
            continue
        if name in helper_names and name.startswith("_"):
            pieces[name] = text

    call_args = _extract_pick_call_args(backup_src)

    flatten_present = "flatten_filled_leg" in backup_src
    return {
        "pieces": pieces,
        "call_args": call_args,
        "flatten_present": flatten_present,
        "missing_required": missing_required,
    }


def _already_has_def(gtc_src: str, name: str) -> bool:
    return bool(re.search(rf"(?m)^def {re.escape(name)}\s*\(", gtc_src)) or bool(
        re.search(rf"(?m)^{re.escape(name)}\s*=", gtc_src)
    )


def _insert_before_ordered_outcomes(gtc_src: str, block: str) -> str:
    marker = "\ndef ordered_outcomes("
    idx = gtc_src.find(marker)
    if idx < 0:
        # Fall back: before execute_locks
        marker2 = "\ndef execute_locks("
        idx = gtc_src.find(marker2)
        if idx < 0:
            raise MergeError(
                "Could not find ordered_outcomes or execute_locks insertion point in GTC file."
            )
        return gtc_src[:idx] + "\n\n" + block.rstrip() + "\n" + gtc_src[idx:]
    return gtc_src[:idx] + "\n\n" + block.rstrip() + "\n" + gtc_src[idx:]


def _patch_send_order(gtc_src: str, call_args: str | None) -> tuple[str, str]:
    """Replace outcomes = ordered_outcomes(...) with _pick_hard_leg when possible."""
    if "_pick_hard_leg" in gtc_src and PICK_CALL_RE.search(gtc_src):
        return gtc_src, "already uses outcomes = _pick_hard_leg(...)"

    m = ORDERED_CALL_RE.search(gtc_src)
    if not m:
        # Maybe backup style already partially present
        if "ordered_outcomes(" not in gtc_src and "_pick_hard_leg(" in gtc_src:
            return gtc_src, "no ordered_outcomes call; _pick_hard_leg already referenced"
        raise MergeError(
            "Could not find 'outcomes = ordered_outcomes(...)' in GTC execute path.\n"
            "Paste thin-first call site manually, then re-check with findstr."
        )
    indent = m.group(1)
    gtc_args = _bare_call_args(m.group(2))
    args = _bare_call_args(call_args) if call_args is not None else gtc_args
    # Common trading-PC signature mirrors ordered_outcomes(cand, fresh)
    if not args:
        args = gtc_args or "cand, fresh"
    # Guard: never emit typed-parameter call syntax.
    if ":" in args:
        raise MergeError(
            f"Refusing to patch send order with typed args {args!r}. "
            "Expected bare names like 'cand, fresh'."
        )
    replacement = f"{indent}outcomes = _pick_hard_leg({args})"
    new_src = ORDERED_CALL_RE.sub(replacement, gtc_src, count=1)
    try:
        ast.parse(replacement.lstrip())
    except SyntaxError as exc:
        raise MergeError(
            "Patched send-order line is not valid Python: "
            f"{replacement!r} ({exc})"
        ) from exc
    return new_src, f"patched send order → outcomes = _pick_hard_leg({args})"


def merge(backup_src: str, gtc_src: str) -> tuple[str, list[str]]:
    """Return merged source + human notes. Raises MergeError on failure."""
    notes: list[str] = []
    clean, n_conflicts, conflict_notes = strip_conflict_markers(backup_src)
    notes.append(f"conflict markers resolved: {n_conflicts}")
    notes.extend(conflict_notes)

    if "<<<<<<<" in clean or "=======" in clean or ">>>>>>>" in clean:
        raise MergeError(
            "Conflict markers remain after strip — backup is too messy to auto-merge."
        )

    extracted = extract_thin_pieces(clean)
    if extracted["missing_required"]:
        raise MergeError(
            "Missing required thin-first defs in backup: "
            + ", ".join(extracted["missing_required"])
        )

    pieces: dict[str, str] = extracted["pieces"]
    notes.append(f"extracted symbols: {', '.join(sorted(pieces))}")

    # Verify GTC keeps required symbols (we start from GTC and only add thin bits).
    for sym in (
        "_with_tif",
        "ONE_LEG_GTC_WAIT_SEC",
        "CHEAP_EXIT_MAX",
        "tick_one_leg_gtc_watches",
        "cancel_second_leg_gtc_on_resolve",
        "orders_enabled",
    ):
        if sym not in gtc_src:
            raise MergeError(
                f"Current live_lock_orders.py is missing GTC symbol {sym!r}. "
                "Run step 1 first (git checkout --theirs for the clean GTC file)."
            )

    merged = gtc_src
    # Inject constants before defs so readers see VENUE_MISS_RANK above helpers.
    assign_names = [n for n in pieces if n in EXTRACT_ASSIGNS]
    def_names = [n for n in pieces if n not in EXTRACT_ASSIGNS]
    # Prefer known helper order: size helpers before _pick_hard_leg before flatten.
    preferred_defs = [
        n
        for n in (
            "_leg_size",
            "_hard_leg_key",
            "_hard_leg_size",
            "_venue_miss_rank",
            "_quote_size_for_leg",
            "_leg_quote_size",
            "_thin_first_outcomes",
            "hard_first_outcomes",
            "_pick_hard_leg",
            "flatten_filled_leg",
        )
        if n in pieces
    ]
    for n in def_names:
        if n not in preferred_defs:
            preferred_defs.append(n)

    insert_blocks: list[str] = []
    for name in assign_names + preferred_defs:
        text = pieces[name]
        if _already_has_def(merged, name):
            notes.append(f"skip inject {name}: already present in GTC file")
            continue
        insert_blocks.append(text.rstrip() + "\n")
        notes.append(f"inject {name}")

    if insert_blocks:
        block = "\n".join(insert_blocks)
        header = (
            "# --- thin-first (merged from tools/_merge_backup/live_lock_orders.py) ---\n"
        )
        merged = _insert_before_ordered_outcomes(merged, header + block)

    merged, patch_note = _patch_send_order(merged, extracted["call_args"])
    notes.append(patch_note)

    # Sanity: must still have GTC + thin
    for sym in ("_pick_hard_leg", "_with_tif", "ONE_LEG_GTC_WAIT_SEC", "_send_pair"):
        if sym not in merged:
            raise MergeError(f"Post-merge sanity failed: missing {sym!r}")

    # Syntax check — include ±5 lines so the FAIL message shows what broke.
    try:
        ast.parse(merged)
    except SyntaxError as exc:
        ctx = _syntax_error_context(merged, exc, radius=5)
        raise MergeError(
            f"Merged file has syntax error: {ctx}\n"
            "Refusing to write. Restore from "
            "tools/_merge_backup/live_lock_orders.before_thin_merge.py"
        ) from exc

    if extracted["flatten_present"] and "flatten_filled_leg" not in merged:
        notes.append(
            "WARNING: backup mentioned flatten_filled_leg but it was not injected "
            "(no extractable top-level def). Check backup manually."
        )

    return merged, notes


def verify_text(src: str) -> list[tuple[str, bool]]:
    checks = [
        ("_pick_hard_leg", "_pick_hard_leg" in src),
        ("_with_tif", "_with_tif" in src),
        ("ONE_LEG_GTC_WAIT_SEC", "ONE_LEG_GTC_WAIT_SEC" in src),
        ("CHEAP_EXIT_MAX", "CHEAP_EXIT_MAX" in src),
        ("tick_one_leg_gtc_watches", "tick_one_leg_gtc_watches" in src),
        ("cancel_second_leg_gtc_on_resolve", "cancel_second_leg_gtc_on_resolve" in src),
        ("orders_enabled", "orders_enabled" in src),
        ("outcomes = _pick_hard_leg", "outcomes = _pick_hard_leg" in src),
    ]
    # flatten is nice-to-have
    checks.append(("flatten_filled_leg (optional)", "flatten_filled_leg" in src))
    return checks


# ---------------------------------------------------------------------------
# Synthetic fixture for --self-test / CI (no real trading-PC backup needed)
# ---------------------------------------------------------------------------

SYNTHETIC_BACKUP = '''\
"""Synthetic conflicted thin-first + GTC stub for merge self-test."""
from decimal import Decimal

NET_MAX = Decimal("0.984")
VENUE_MISS_RANK = {"gemini": 0, "kalshi": 1, "polymarket": 2}

<<<<<<< HEAD
def _leg_size(cand: dict, outcome: str):
    key = "yes_size" if outcome == "yes" else "no_size"
    try:
        return Decimal(str(cand.get(key) or "0"))
    except Exception:
        return Decimal("0")


def _pick_hard_leg(cand: dict, fresh: list[dict]) -> list[str]:
    """Thin/hard first: smaller size, then miss-venue rank, then pricier cash."""
    yes_sz = _leg_size(cand, "yes")
    no_sz = _leg_size(cand, "no")
    if yes_sz < no_sz:
        return ["yes", "no"]
    if no_sz < yes_sz:
        return ["no", "yes"]
    yv = str(cand.get("yes_venue") or "").lower()
    nv = str(cand.get("no_venue") or "").lower()
    yr = VENUE_MISS_RANK.get(yv, 99)
    nr = VENUE_MISS_RANK.get(nv, 99)
    if yr < nr:
        return ["yes", "no"]
    if nr < yr:
        return ["no", "yes"]
    yp = Decimal(str(cand.get("yes_price") or "0"))
    np_ = Decimal(str(cand.get("no_price") or "0"))
    if yp >= np_:
        return ["yes", "no"]
    return ["no", "yes"]


def flatten_filled_leg(log, filled_spec: dict):
    """Same-shop opposite IOC (synthetic stub)."""
    return None
=======
def ordered_outcomes(cand, fresh):
    return ["yes", "no"]

ONE_LEG_GTC_WAIT_SEC = 180
>>>>>>> origin/main

def execute_locks(cand, fresh):
<<<<<<< HEAD
    outcomes = _pick_hard_leg(cand, fresh)  # thin-first
=======
    outcomes = ordered_outcomes(cand, fresh)
>>>>>>> origin/main
    return outcomes
'''

# Realistic full-file-shaped backup: annotated def + trailing-comment call +
# conflict markers around pick / flatten / send path. Used to catch the class of
# bug that produced "invalid syntax (... line 1228)" on Paul's trading PC.
REALISTIC_THIN_DEFS = '''\
VENUE_MISS_RANK = {"gemini": 0, "kalshi": 1, "polymarket": 2}


def _leg_size(cand: dict, outcome: str):
    key = "yes_size" if outcome == "yes" else "no_size"
    try:
        return Decimal(str(cand.get(key) or "0"))
    except Exception:
        return Decimal("0")


def _pick_hard_leg(cand: dict, fresh: list[dict]) -> list[str]:
    """Thin/hard first: smaller size, then miss-venue rank, then pricier cash."""
    yes_sz = _leg_size(cand, "yes")
    no_sz = _leg_size(cand, "no")
    if yes_sz < no_sz:
        return ["yes", "no"]
    if no_sz < yes_sz:
        return ["no", "yes"]
    yv = str(cand.get("yes_venue") or "").lower()
    nv = str(cand.get("no_venue") or "").lower()
    yr = VENUE_MISS_RANK.get(yv, 99)
    nr = VENUE_MISS_RANK.get(nv, 99)
    if yr < nr:
        return ["yes", "no"]
    if nr < yr:
        return ["no", "yes"]
    yp = Decimal(str(cand.get("yes_price") or "0"))
    np_ = Decimal(str(cand.get("no_price") or "0"))
    if yp >= np_:
        return ["yes", "no"]
    return ["no", "yes"]


def flatten_filled_leg(log, filled_spec: dict):
    """Same-shop opposite IOC (synthetic stub)."""
    return None
'''


def build_realistic_conflicted_backup(gtc_src: str) -> str:
    """Wrap thin-first defs + send-path call as conflict hunks inside a GTC body.

    Mirrors a mid-merge `tools/_merge_backup/live_lock_orders.py` without needing
    Paul's private backup: conflict around `_pick_hard_leg` / `flatten_filled_leg`
    vs `ordered_outcomes`, and around the execute_locks send-order line.
    """
    try:
        tree = ast.parse(gtc_src)
    except SyntaxError as exc:
        raise MergeError(f"GTC source not valid Python for fixture build: {exc}") from exc
    lines = gtc_src.splitlines(keepends=True)
    oo = next(
        (
            n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "ordered_outcomes"
        ),
        None,
    )
    if oo is None:
        raise MergeError("GTC fixture build: ordered_outcomes not found")
    start, end = oo.lineno, getattr(oo, "end_lineno", None) or oo.lineno
    theirs = "".join(lines[start - 1 : end])
    conflicted = (
        lines[: start - 1]
        + ["<<<<<<< HEAD\n"]
        + [REALISTIC_THIN_DEFS if REALISTIC_THIN_DEFS.endswith("\n") else REALISTIC_THIN_DEFS + "\n"]
        + ["=======\n"]
        + [theirs]
        + [">>>>>>> origin/main\n"]
        + lines[end:]
    )
    text = "".join(conflicted)
    old_call = "        outcomes = ordered_outcomes(cand, fresh)\n"
    new_call = (
        "<<<<<<< HEAD\n"
        "        outcomes = _pick_hard_leg(cand, fresh)  # thin-first\n"
        "=======\n"
        "        outcomes = ordered_outcomes(cand, fresh)\n"
        ">>>>>>> origin/main\n"
    )
    if old_call not in text:
        raise MergeError(
            "GTC fixture build: execute_locks ordered_outcomes call not found"
        )
    return text.replace(old_call, new_call, 1)

SYNTHETIC_GTC = '''\
"""Synthetic clean GTC stub (mirrors symbols the merger requires)."""
from decimal import Decimal

NET_MAX = Decimal("0.95")
ONE_LEG_GTC_WAIT_SEC = 180
CHEAP_EXIT_MAX = Decimal("0.25")

def orders_enabled():
    return False

def _with_tif(spec, tif):
    out = dict(spec)
    out["tif"] = tif
    return out

def ordered_outcomes(cand, fresh):
    return ["yes", "no"]

def execute_locks(scan, sport, title, game, result, fresh, log):
    cand = (result.get("candidates") or [{}])[0]
    outcomes = ordered_outcomes(cand, fresh)
    return outcomes

def tick_one_leg_gtc_watches(log):
    return []

def cancel_second_leg_gtc_on_resolve(log, key):
    return None

def _send_pair(log, key, title, legs):
    first, second = legs[0], _with_tif(legs[1], "gtc")
    return first, second
'''


def self_test() -> int:
    print("=== merge_thin_first_into_gtc self-test ===")
    try:
        merged, notes = merge(SYNTHETIC_BACKUP, SYNTHETIC_GTC)
    except MergeError as exc:
        print(f"FAIL: {exc}")
        return 1
    for note in notes:
        print(f"  note: {note}")
    checks = verify_text(merged)
    # Optional flatten should be present in synthetic
    fail = False
    required_ok = {
        "_pick_hard_leg",
        "_with_tif",
        "ONE_LEG_GTC_WAIT_SEC",
        "CHEAP_EXIT_MAX",
        "tick_one_leg_gtc_watches",
        "cancel_second_leg_gtc_on_resolve",
        "orders_enabled",
        "outcomes = _pick_hard_leg",
    }
    for name, ok in checks:
        base = name.split(" (")[0]
        if base in required_ok or name in required_ok:
            status = "OK" if ok else "FAIL"
            if not ok:
                fail = True
            print(f"  [{status}] {name}")
        else:
            print(f"  [{'OK' if ok else 'MISS'}] {name}")
    if "def _pick_hard_leg" not in merged:
        print("  [FAIL] injected def _pick_hard_leg missing")
        fail = True
    if "def flatten_filled_leg" not in merged:
        print("  [FAIL] injected def flatten_filled_leg missing")
        fail = True
    if "VENUE_MISS_RANK" not in merged:
        print("  [FAIL] VENUE_MISS_RANK missing")
        fail = True
    # Ensure we did not drop GTC send_pair
    if "def _send_pair" not in merged:
        print("  [FAIL] _send_pair missing")
        fail = True
    # Failure path: backup without thin-first must raise
    try:
        merge("x = 1\n", SYNTHETIC_GTC)
        print("  [FAIL] expected MergeError on empty backup")
        fail = True
    except MergeError:
        print("  [OK] loud fail when backup lacks _pick_hard_leg")

    # Regression: annotated def + trailing-comment call must NOT patch typed args.
    annotated_only = (
        "def _pick_hard_leg(cand: dict, fresh: list[dict]) -> list[str]:\n"
        "    return ['yes', 'no']\n"
        "\n"
        "def execute_locks():\n"
        "    outcomes = _pick_hard_leg(cand, fresh)  # thin-first\n"
    )
    args = _extract_pick_call_args(annotated_only)
    if args != "cand, fresh":
        print(f"  [FAIL] call_args from annotated+comment expected 'cand, fresh' got {args!r}")
        fail = True
    else:
        print("  [OK] call_args strips/ignores typed def when call has trailing comment")

    def_only = (
        "def _pick_hard_leg(cand: dict, fresh: list[dict]) -> list[str]:\n"
        "    return ['yes', 'no']\n"
    )
    args2 = _extract_pick_call_args(def_only)
    if args2 != "cand, fresh":
        print(f"  [FAIL] def-only call_args expected bare names got {args2!r}")
        fail = True
    else:
        print("  [OK] def-only annotated signature → bare call args")

    # Realistic full-file conflicted backup → clean GTC must ast.parse.
    gtc_path = DEFAULT_GTC
    if gtc_path.is_file():
        gtc_full = gtc_path.read_text(encoding="utf-8")
        try:
            realistic_backup = build_realistic_conflicted_backup(gtc_full)
            merged_full, notes_full = merge(realistic_backup, gtc_full)
            ast.parse(merged_full)
            if "outcomes = _pick_hard_leg(cand, fresh)" not in merged_full:
                print("  [FAIL] realistic merge missing patched send order")
                fail = True
            elif "cand: dict" in merged_full.split("outcomes = _pick_hard_leg", 1)[-1][:80]:
                print("  [FAIL] realistic merge patched typed args into call")
                fail = True
            elif "def _pick_hard_leg" not in merged_full or "def flatten_filled_leg" not in merged_full:
                print("  [FAIL] realistic merge missing injected defs")
                fail = True
            else:
                print("  [OK] realistic full-file conflicted backup merges + ast.parse")
                for n in notes_full:
                    if n.startswith("patched") or n.startswith("inject"):
                        print(f"    note: {n}")
        except MergeError as exc:
            print(f"  [FAIL] realistic full-file merge: {exc}")
            fail = True
        except SyntaxError as exc:
            print(f"  [FAIL] realistic merged output SyntaxError: {exc}")
            fail = True
    else:
        print("  [MISS] skip realistic full-file test (no tools/live_lock_orders.py)")

    # Syntax-error reporter must include context lines
    try:
        bad = "a = 1\nburst (\n"
        ast.parse(bad)
    except SyntaxError as se:
        ctx = _syntax_error_context(bad, se, radius=5)
        if ">>" not in ctx or "burst" not in ctx:
            print(f"  [FAIL] syntax context missing markers: {ctx!r}")
            fail = True
        else:
            print("  [OK] syntax-error context includes ± lines")

    if fail:
        print("SELF-TEST FAIL")
        return 1
    print("SELF-TEST OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    ap.add_argument("--gtc", type=Path, default=DEFAULT_GTC)
    ap.add_argument("--out", type=Path, default=None, help="Defaults to --gtc")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Merge and print summary; do not write --out",
    )
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="Run synthetic conflict-marker merge smoke test and exit",
    )
    ap.add_argument(
        "--no-before-backup",
        action="store_true",
        help="Skip writing live_lock_orders.before_thin_merge.py",
    )
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    backup = args.backup
    gtc = args.gtc
    out = args.out or gtc

    print("=== merge thin-first into GTC ===")
    print(f"backup: {backup}")
    print(f"gtc:    {gtc}")
    print(f"out:    {out}{' (dry-run)' if args.dry_run else ''}")

    if not backup.is_file():
        print(
            "FAIL: backup missing.\n"
            f"  Expected: {backup}\n"
            "  Step 1 should have copied the conflicted live_lock_orders.py there\n"
            "  before `git checkout --theirs`. Restore that copy, then re-run."
        )
        return 2
    if not gtc.is_file():
        print(f"FAIL: GTC file missing: {gtc}")
        return 2

    backup_src = backup.read_text(encoding="utf-8")
    gtc_src = gtc.read_text(encoding="utf-8")

    try:
        merged, notes = merge(backup_src, gtc_src)
    except MergeError as exc:
        print(f"FAIL: {exc}")
        return 1

    for note in notes:
        print(f"  {note}")

    if not args.dry_run:
        if not args.no_before_backup and out.resolve() == gtc.resolve():
            BEFORE_BACKUP.parent.mkdir(parents=True, exist_ok=True)
            BEFORE_BACKUP.write_text(gtc_src, encoding="utf-8")
            print(f"  wrote before-backup: {BEFORE_BACKUP}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(merged, encoding="utf-8", newline="\n")
        print(f"  wrote: {out}")
    else:
        # Still exercise write to a temp for syntax/size sanity in dry-run
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".py", delete=False
        ) as tmp:
            tmp.write(merged)
            print(f"  dry-run temp bytes={len(merged)} path={tmp.name}")

    print("--- verify ---")
    ok_all = True
    for name, ok in verify_text(merged):
        optional = "optional" in name
        if ok:
            print(f"  [OK] {name}")
        elif optional:
            print(f"  [MISS optional] {name}")
        else:
            print(f"  [FAIL] {name}")
            ok_all = False

    if not ok_all:
        print("FAIL: post-merge symbol checks failed")
        return 1
    print("OK: thin-first merged into GTC without dropping GTC symbols")
    return 0


if __name__ == "__main__":
    sys.exit(main())
