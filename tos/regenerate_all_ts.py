"""Regenerate all thinkScript studies and copy generators to drive/tos."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT.parent / "drive" / "tos"

GENERATORS = [
    "gen_googl_ts.py",
    "gen_amzn_ts.py",
    "gen_tsla_ts.py",
    "gen_nvda_ts.py",
    "gen_meta_ts.py",
    "gen_msft_ts.py",
    "gen_au_ts.py",
    "gen_aapl_ts.py",
    "gen_amd_ts.py",
    "gen_nflx_ts.py",
]


def main() -> None:
    import runpy

    DRIVE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "ts_common.py", DRIVE / "ts_common.py")
    print(f"Copied ts_common.py -> {DRIVE / 'ts_common.py'}")
    for name in GENERATORS:
        path = ROOT / name
        runpy.run_path(str(path), run_name="__main__")
        shutil.copy2(path, DRIVE / name)
        print(f"Copied {name} -> {DRIVE / name}")
    print("Done.")


if __name__ == "__main__":
    main()
