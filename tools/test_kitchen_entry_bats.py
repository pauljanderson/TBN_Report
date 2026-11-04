"""Gate: kitchen entry bats stay at repo root and stay pull-discoverable.

Paul problem class (2026-11-04): PR #49 merged run_rebuild_kitchen_dashboard.bat
onto origin/main; Paul ran the bat from C:\\...\\stockresearch before git pull,
so Windows said 'not recognized'. Class bugs this catches:

  - bat promised in a PR / chat but never committed at repo root
  - bat renamed / nested under tools/ so the documented name breaks
  - bat loses the python one-liner fallback Paul can run when the .bat
    is not on disk yet

Does not place, cancel, or sell. No secrets. No network.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ROOT_BATS = (
    "run_rebuild_kitchen_dashboard.bat",
    "run_dashboard_stamp_gate.bat",
    "git_pull.bat",
)

# One-liner Paul can run when the bat is not on disk yet (pre-pull).
PYTHON_FALLBACK = r"python tools\write_orders_performance.py"
# Writer entry the rebuild bat must invoke.
WRITER_INVOKE = "write_orders_performance.py"


def _read(name: str) -> str:
    path = ROOT / name
    assert path.is_file(), f"missing repo-root bat: {name}"
    return path.read_text(encoding="utf-8", errors="replace")


def test_kitchen_entry_bats_exist_at_repo_root():
    for name in REQUIRED_ROOT_BATS:
        path = ROOT / name
        assert path.is_file(), f"{name} must live at repo root (not tools/)"
        assert not (ROOT / "tools" / name).is_file(), (
            f"{name} must not be nested only under tools/"
        )


def test_rebuild_bat_calls_writer_and_prints_python_fallback():
    text = _read("run_rebuild_kitchen_dashboard.bat")
    assert WRITER_INVOKE in text, "rebuild bat must call write_orders_performance"
    assert PYTHON_FALLBACK in text, (
        "rebuild bat must print the python one-liner for pre-pull / missing-bat"
    )
    assert "dashboard.html" in text, "rebuild bat must name the stamp path"
    assert "git pull" in text.lower(), (
        "rebuild bat must tell Paul to git pull when the bat is missing"
    )


def test_git_pull_calls_rebuild_when_tape_present():
    text = _read("git_pull.bat")
    assert "run_rebuild_kitchen_dashboard.bat" in text, (
        "git_pull.bat must call rebuild so merge≠HTML never recurs"
    )
    assert "git pull origin main" in text


def test_stamp_gate_bat_present():
    text = _read("run_dashboard_stamp_gate.bat")
    assert "dashboard_stamp_gate.py" in text


if __name__ == "__main__":
    test_kitchen_entry_bats_exist_at_repo_root()
    test_rebuild_bat_calls_writer_and_prints_python_fallback()
    test_git_pull_calls_rebuild_when_tape_present()
    test_stamp_gate_bat_present()
    print("test_kitchen_entry_bats ok")
