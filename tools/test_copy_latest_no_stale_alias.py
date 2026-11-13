"""Regression: Copy-LatestRunOutputs.ps1 must not keep a stale *_LatestRun_<stem>.csv alias.

Bug (2026-11-06 DailyRun): YH/MTS/WPBR/RS wrote no Scanner_<ts>.csv (no signals), the copy
step only warned "Missing ... (skipped)", and the old YH_LatestRun_Scanner.csv (Oct 26) /
RS_LatestRun_Scanner.csv (Oct 23) stayed. generate_system_convergence_report.py prefers the
LatestRun alias, so stale scanner rows were published as current.

Contract: when this run's stamped file is missing, the alias is removed.

Run: python tools/test_copy_latest_no_stale_alias.py   (Windows, or WSL with powershell.exe)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Copy-LatestRunOutputs.ps1"
TS = "261107000000"
HDR = "SYMBOL,DATE,CLOSE\n"


def _win(p: Path) -> str:
    if os.name == "nt":
        return str(p)
    return subprocess.check_output(["wslpath", "-w", str(p)], text=True).strip()


def _powershell() -> str | None:
    for exe in ("powershell.exe", "powershell", "pwsh"):
        if shutil.which(exe):
            return exe
    return None


def test_missing_stamped_file_removes_stale_alias() -> None:
    ps = _powershell()
    if ps is None:
        print("SKIP no powershell on PATH")
        return
    # Under local/ (gitignored) so the folder is reachable from both WSL and Windows.
    base = ROOT / "local"
    base.mkdir(exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="test_copy_latest_", dir=base))
    try:
        for stem in ("Closed", "Open", "Watchlist", "Summary"):  # no Scanner this run
            (d / f"BRT_{stem}_{TS}.csv").write_text(HDR + "AAA,2026-11-06,1\n")
        (d / f"RL_Closed_{TS}.csv").write_text(HDR)
        stale = d / "BRT_LatestRun_Scanner.csv"
        stale.write_text(HDR + "OLD,2026-10-23,9\n")

        try:
            r = subprocess.run(
                [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", _win(SCRIPT),
                 "-OutputDir", _win(d)],
                capture_output=True, text=True, timeout=180,
            )
        except OSError as e:  # WSL with Windows interop disabled
            print(f"SKIP cannot launch {ps}: {e}")
            return
        out = r.stdout + r.stderr
        assert r.returncode == 0, f"copy script failed rc={r.returncode}\n{out}"
        assert (d / "BRT_LatestRun_Closed.csv").is_file(), out
        assert not stale.exists(), f"stale BRT_LatestRun_Scanner.csv survived\n{out}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_missing_stamped_file_removes_stale_alias()
    except AssertionError as e:
        print(f"FAIL test_missing_stamped_file_removes_stale_alias: {e}")
        return 1
    print("PASS test_copy_latest_no_stale_alias.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
