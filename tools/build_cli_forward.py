#!/usr/bin/env python3

"""Normalize run_*.bat forward argv for rocket_tbn / standalones.



CMD/batch treat '=' and ',' as argument delimiters, so:

  run_rl.bat -v aggressive_sell=average

arrives as: ['-v', 'aggressive_sell', 'average']

  run_vz.bat -s NVDA,AAPL

arrives as: ['-s', 'NVDA', 'AAPL']



This rejoins after -v/--set into a single KEY=VALUE token, and after

-s/--symbols into a single comma-separated symbol list.



Usage (from build_cli_forward.bat):

  set BUILD_CLI_FORWARD_UNIV=<univ or empty>

  python build_cli_forward.py OUTVAR [launcher args...]

Prints one Windows cmdline fragment to stdout (list2cmdline).

"""

from __future__ import annotations



import os

import subprocess

import sys





def strip_universe(univ: str, args: list[str]) -> list[str]:

    if not univ:

        return list(args)

    if not args:

        return []

    if args[0].lower() == "-s" and len(args) >= 2:

        return args[2:]

    return args[1:]





def rejoin_v_splits(args: list[str]) -> list[str]:

    out: list[str] = []

    i = 0

    n = len(args)

    while i < n:

        a = args[i]

        if a in ("-v", "--set") and i + 1 < n:

            key = args[i + 1]

            if "=" not in key and i + 2 < n:

                out.append(a)

                out.append(f"{key}={args[i + 2]}")

                i += 3

                continue

            out.append(a)

            out.append(key)

            i += 2

            continue

        out.append(a)

        i += 1

    return out





def rejoin_s_splits(args: list[str]) -> list[str]:

    """Rejoin CMD comma-split -s lists: -s NVDA AAPL → -s NVDA,AAPL."""

    out: list[str] = []

    i = 0

    n = len(args)

    while i < n:

        a = args[i]

        if a in ("-s", "--symbols") and i + 1 < n:

            parts: list[str] = []

            j = i + 1

            while j < n and not str(args[j]).startswith("-"):

                tok = str(args[j]).strip()

                if tok:

                    # Already comma-joined token — keep pieces

                    parts.extend(p for p in tok.split(",") if p.strip())

                j += 1

            if parts:

                out.append(a)

                out.append(",".join(parts))

                i = j

                continue

        out.append(a)

        i += 1

    return out





def main(argv: list[str]) -> int:

    # argv[0]=script, [1]=OUTVAR (ignored), [2:]=launcher args (univ may still lead)

    univ = os.environ.get("BUILD_CLI_FORWARD_UNIV", "")

    launcher = argv[2:] if len(argv) >= 2 else []

    forward = rejoin_s_splits(rejoin_v_splits(strip_universe(univ, launcher)))

    print(subprocess.list2cmdline(forward))

    return 0





if __name__ == "__main__":

    raise SystemExit(main(sys.argv))


