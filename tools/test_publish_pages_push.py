#!/usr/bin/env python3
"""Regression: DailyRun --push must survive origin/main moving mid-run.

2026-08-12 18:30 ET DailyRun failed at publish: WRL commits landed on origin/main
while the Windows job was still running, so a bare `git push` was rejected.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_MOD_PATH = _REPO / "scripts" / "publish_github_pages.py"
_spec = importlib.util.spec_from_file_location("publish_github_pages", _MOD_PATH)
assert _spec and _spec.loader
pages = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pages)


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed ({proc.returncode}): {(proc.stderr or proc.stdout).strip()}"
        )
    return proc


def _init_user(cwd: Path) -> None:
    _git(["config", "user.email", "dailyrun-test@example.com"], cwd)
    _git(["config", "user.name", "DailyRun Test"], cwd)
    _git(["config", "pull.rebase", "false"], cwd)


def _clone(origin: Path, dest: Path) -> Path:
    _git(["clone", str(origin), str(dest)], origin.parent)
    _init_user(dest)
    return dest


def _seed_origin(tmp: Path) -> Path:
    origin = tmp / "origin.git"
    origin.mkdir()
    _git(["init", "--bare", "-b", "main"], origin)
    seed = tmp / "seed"
    _git(["clone", str(origin), str(seed)], tmp)
    _init_user(seed)
    (seed / "docs").mkdir()
    (seed / "docs" / "investment.html").write_text("reports-v1\n", encoding="utf-8")
    _git(["add", "docs/investment.html"], seed)
    _git(["commit", "-m", "Update reports 2026-08-12 17:27"], seed)
    _git(["push", "-u", "origin", "main"], seed)
    shutil.rmtree(seed)
    return origin


def test_push_survives_origin_main_moving_mid_run(tmp: Path) -> None:
    """Local DailyRun commit + remote WRL commit → publish still updates origin/main."""
    origin = _seed_origin(tmp)
    daily = _clone(origin, tmp / "dailyrun")
    cloud = _clone(origin, tmp / "cloud")

    (cloud / "stock_analysis").mkdir()
    (cloud / "stock_analysis" / "rocket_wrl.py").write_text("# wrl\n", encoding="utf-8")
    _git(["add", "stock_analysis/rocket_wrl.py"], cloud)
    _git(["commit", "-m", "Add WRL weekly range/swing demand-zone system."], cloud)
    _git(["push", "origin", "main"], cloud)

    (daily / "docs" / "investment.html").write_text("reports-v2-eod\n", encoding="utf-8")
    pages.git_push_docs(daily, daily / "docs", "Update reports 2026-08-12 21:10")

    log = _git(["log", "--oneline", "--all"], origin).stdout
    assert "Add WRL weekly range/swing" in log, log
    assert "Update reports 2026-08-12 21:10" in log, log

    check = _clone(origin, tmp / "verify")
    assert (check / "stock_analysis" / "rocket_wrl.py").is_file()
    assert (check / "docs" / "investment.html").read_text(encoding="utf-8") == "reports-v2-eod\n"


def test_push_when_behind_with_no_docs_commit(tmp: Path) -> None:
    """No new docs, but origin/main moved: --push must pull instead of failing."""
    origin = _seed_origin(tmp)
    daily = _clone(origin, tmp / "dailyrun")
    cloud = _clone(origin, tmp / "cloud")
    (cloud / "README.md").write_text("wrl note\n", encoding="utf-8")
    _git(["add", "README.md"], cloud)
    _git(["commit", "-m", "Document WRL engine rules"], cloud)
    _git(["push", "origin", "main"], cloud)

    pages.git_push_docs(daily, daily / "docs", "Update reports unused")
    log = _git(["log", "--oneline", "main"], origin).stdout
    assert "Document WRL engine rules" in log, log


def test_old_bare_push_would_reject(tmp: Path) -> None:
    """Sanity: the pre-fix `git push origin main` is a non-fast-forward."""
    origin = _seed_origin(tmp)
    daily = _clone(origin, tmp / "dailyrun")
    cloud = _clone(origin, tmp / "cloud")
    (cloud / "wrl.txt").write_text("x\n", encoding="utf-8")
    _git(["add", "wrl.txt"], cloud)
    _git(["commit", "-m", "WRL"], cloud)
    _git(["push", "origin", "main"], cloud)

    (daily / "docs" / "investment.html").write_text("local\n", encoding="utf-8")
    _git(["add", "docs/investment.html"], daily)
    _git(["commit", "-m", "Update reports local"], daily)
    proc = _git(["push", "origin", "main"], daily, check=False)
    assert proc.returncode != 0, "bare push should be rejected when origin/main moved"
    err = (proc.stderr or proc.stdout).lower()
    assert "non-fast-forward" in err or "rejected" in err or "fetch first" in err, err


def test_push_docs_conflict_falls_back_to_merge(tmp: Path) -> None:
    """Both sides edited the same report: rebase conflicts, merge -X ours keeps DailyRun docs."""
    origin = _seed_origin(tmp)
    daily = _clone(origin, tmp / "dailyrun")
    cloud = _clone(origin, tmp / "cloud")
    (cloud / "docs" / "investment.html").write_text("cloud-wrl-touch\n", encoding="utf-8")
    (cloud / "wrl.txt").write_text("engine\n", encoding="utf-8")
    _git(["add", "docs/investment.html", "wrl.txt"], cloud)
    _git(["commit", "-m", "WRL plus docs tweak"], cloud)
    _git(["push", "origin", "main"], cloud)

    (daily / "docs" / "investment.html").write_text("dailyrun-eod\n", encoding="utf-8")
    pages.git_push_docs(daily, daily / "docs", "Update reports conflict")

    check = _clone(origin, tmp / "verify")
    assert (check / "wrl.txt").read_text(encoding="utf-8") == "engine\n"
    assert (check / "docs" / "investment.html").read_text(encoding="utf-8") == "dailyrun-eod\n"


if __name__ == "__main__":
    tests = [
        test_old_bare_push_would_reject,
        test_push_survives_origin_main_moving_mid_run,
        test_push_when_behind_with_no_docs_commit,
        test_push_docs_conflict_falls_back_to_merge,
    ]
    failed = 0
    for fn in tests:
        tmp = Path(tempfile.mkdtemp(prefix="pages-push-"))
        try:
            fn(tmp)
            print(f"ok  {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
            raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(failed)
