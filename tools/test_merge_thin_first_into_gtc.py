"""Smoke tests for tools/merge_thin_first_into_gtc.py (no network, no secrets)."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "merge_thin_first_into_gtc.py"
GTC = ROOT / "tools" / "live_lock_orders.py"


def _load():
    spec = importlib.util.spec_from_file_location("merge_thin_first_into_gtc", HELPER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_self_test_passes():
    mod = _load()
    assert mod.self_test() == 0


def test_strip_prefers_ours_for_thin():
    mod = _load()
    text = (
        "a = 1\n"
        "<<<<<<< HEAD\n"
        "def _pick_hard_leg(cand, fresh):\n"
        "    return ['yes', 'no']\n"
        "=======\n"
        "def ordered_outcomes(cand, fresh):\n"
        "    return ['yes', 'no']\n"
        ">>>>>>> origin/main\n"
        "b = 2\n"
    )
    clean, n, notes = mod.strip_conflict_markers(text)
    assert n == 1
    assert "_pick_hard_leg" in clean
    assert "ordered_outcomes" not in clean or "def ordered_outcomes" not in clean
    assert "ours(thin)" in notes[0]


def test_strip_prefers_theirs_for_gtc_only_hunk():
    mod = _load()
    text = (
        "<<<<<<< HEAD\n"
        "OLD = 1\n"
        "=======\n"
        "ONE_LEG_GTC_WAIT_SEC = 180\n"
        "def _with_tif(spec, tif):\n"
        "    return spec\n"
        ">>>>>>> origin/main\n"
    )
    clean, n, notes = mod.strip_conflict_markers(text)
    assert n == 1
    assert "ONE_LEG_GTC_WAIT_SEC" in clean
    assert "theirs(gtc)" in notes[0]


def test_loud_fail_without_pick_hard_leg():
    mod = _load()
    try:
        mod.merge("x = 1\n", mod.SYNTHETIC_GTC)
    except mod.MergeError as exc:
        assert "_pick_hard_leg" in str(exc)
    else:
        raise AssertionError("expected MergeError")


def test_merge_keeps_gtc_and_injects_thin():
    mod = _load()
    merged, notes = mod.merge(mod.SYNTHETIC_BACKUP, mod.SYNTHETIC_GTC)
    assert "def _pick_hard_leg" in merged
    assert "def flatten_filled_leg" in merged
    assert "VENUE_MISS_RANK" in merged
    assert "ONE_LEG_GTC_WAIT_SEC" in merged
    assert "def _with_tif" in merged
    assert "def tick_one_leg_gtc_watches" in merged
    assert "outcomes = _pick_hard_leg" in merged
    assert "outcomes = _pick_hard_leg(cand: dict" not in merged
    assert "<<<<<<<" not in merged
    assert any("inject _pick_hard_leg" in n for n in notes)
    ast.parse(merged)


def test_call_args_skips_annotated_def_when_commented_call_exists():
    """Regression for trading-PC line-1228 SyntaxError.

    Trailing `# thin-first` used to miss PICK_CALL_RE, so the annotated def
    signature was pasted into the call site:
      outcomes = _pick_hard_leg(cand: dict, fresh: list[dict])  # invalid
    """
    mod = _load()
    src = (
        "def _pick_hard_leg(cand: dict, fresh: list[dict]) -> list[str]:\n"
        "    return ['yes', 'no']\n"
        "\n"
        "def execute_locks():\n"
        "    outcomes = _pick_hard_leg(cand, fresh)  # thin-first\n"
    )
    assert mod._extract_pick_call_args(src) == "cand, fresh"
    assert mod._bare_call_args("cand: dict, fresh: list[dict]") == "cand, fresh"


def test_realistic_conflicted_backup_merges_into_real_gtc():
    mod = _load()
    assert GTC.is_file()
    gtc = GTC.read_text(encoding="utf-8")
    backup = mod.build_realistic_conflicted_backup(gtc)
    assert "<<<<<<<" in backup
    assert "_pick_hard_leg" in backup
    assert "flatten_filled_leg" in backup
    merged, notes = mod.merge(backup, gtc)
    ast.parse(merged)
    assert "def _pick_hard_leg" in merged
    assert "def flatten_filled_leg" in merged
    assert "outcomes = _pick_hard_leg(cand, fresh)" in merged
    assert "outcomes = _pick_hard_leg(cand: dict" not in merged
    assert "ONE_LEG_GTC_WAIT_SEC" in merged
    assert "def _send_pair" in merged
    assert any("patched send order" in n for n in notes)


def test_syntax_error_context_shows_nearby_lines():
    mod = _load()
    bad = "ok = 1\nbroken (\n"
    try:
        ast.parse(bad)
    except SyntaxError as exc:
        ctx = mod._syntax_error_context(bad, exc, radius=5)
    assert ">>" in ctx
    assert "broken" in ctx


def test_cli_self_test_main():
    mod = _load()
    assert mod.main(["--self-test"]) == 0


if __name__ == "__main__":
    test_self_test_passes()
    test_strip_prefers_ours_for_thin()
    test_strip_prefers_theirs_for_gtc_only_hunk()
    test_loud_fail_without_pick_hard_leg()
    test_merge_keeps_gtc_and_injects_thin()
    test_call_args_skips_annotated_def_when_commented_call_exists()
    test_realistic_conflicted_backup_merges_into_real_gtc()
    test_syntax_error_context_shows_nearby_lines()
    test_cli_self_test_main()
    print("ok")
