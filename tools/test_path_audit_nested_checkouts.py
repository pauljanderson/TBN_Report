"""Check that the path audit respects checkout boundaries."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "repo_split" / "lib"))
from rewrite_paths import audit


def test_path_audit_nested_checkouts():
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir).resolve()
        (root / ".git").mkdir()
        nested_repo = root / "experiments" / "standalone"
        (nested_repo / ".git").mkdir(parents=True)
        worktree = root / ".claude" / "worktrees" / "research"
        worktree.mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: ../metadata\n", encoding="utf-8")

        primary_launcher = root / "run_daily.bat"
        worktree_launcher = worktree / "run_daily.bat"
        legacy_path = "Downloads/" + "stockresearch"
        for launcher in (primary_launcher, worktree_launcher, nested_repo / "run_daily.bat"):
            launcher.write_text(f'cd /d "{legacy_path}"\n', encoding="utf-8")

        assert [path for path, _ in audit(root)] == [primary_launcher]
        assert [path for path, _ in audit(worktree)] == [worktree_launcher]


def main():
    test_path_audit_nested_checkouts()


if __name__ == "__main__":
    main()
