#!/usr/bin/env python3
"""
ThinkorSwim zone/trade study generator — CLI for Python or frozen .exe.

Examples:
  TOS_Zones_Generator.exe --all
  TOS_Zones_Generator.exe --symbol NVDA --symbol AAPL
  TOS_Zones_Generator.exe --all -o C:\\Users\\me\\Desktop\\tos
  TOS_Zones_Generator.exe -s NFLX --input NFLX.csv
  TOS_Zones_Generator.exe --input-dir .\\my_spreadsheets
  TOS_Zones_Generator.exe --list
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure sibling imports work when frozen (PyInstaller) or run as script.
_TOS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if str(_TOS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOS_DIR))

from ts_common import write_ts_files  # noqa: E402
from ts_input_loader import load_symbol_csv  # noqa: E402

import gen_aapl_ts  # noqa: E402
import gen_amd_ts  # noqa: E402
import gen_amzn_ts  # noqa: E402
import gen_au_ts  # noqa: E402
import gen_googl_ts  # noqa: E402
import gen_meta_ts  # noqa: E402
import gen_msft_ts  # noqa: E402
import gen_nflx_ts  # noqa: E402
import gen_nvda_ts  # noqa: E402
import gen_tsla_ts  # noqa: E402

MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]

_SYMBOL_MODULES = {
    "AAPL": gen_aapl_ts,
    "AMD": gen_amd_ts,
    "AMZN": gen_amzn_ts,
    "AU": gen_au_ts,
    "GOOGL": gen_googl_ts,
    "META": gen_meta_ts,
    "MSFT": gen_msft_ts,
    "NFLX": gen_nflx_ts,
    "NVDA": gen_nvda_ts,
    "TSLA": gen_tsla_ts,
}


def generate_symbol(symbol: str, output_dir: Path) -> None:
    key = symbol.strip().upper()
    mod = _SYMBOL_MODULES.get(key)
    if mod is None:
        raise ValueError(f"Unknown symbol {symbol!r}; expected one of {MARKTEN}")
    extra = getattr(mod, "EXTRA_HEADER", "")
    write_ts_files(
        key,
        mod.zones,
        mod.entries,
        mod.exits,
        output_dir=output_dir,
        extra_header=extra,
    )


def generate_from_csv(path: Path, output_dir: Path, symbol: str | None = None) -> None:
    sym, zones, entries, exits, extra = load_symbol_csv(path, symbol=symbol)
    write_ts_files(
        sym,
        zones,
        entries,
        exits,
        output_dir=output_dir,
        extra_header=extra,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate thinkScript studies (zones + BO + entries/exits) for ThinkorSwim.",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help=f"Generate all MarkTen symbols: {', '.join(MARKTEN)}",
    )
    ap.add_argument(
        "-s",
        "--symbol",
        action="append",
        dest="symbols",
        metavar="SYM",
        help="Generate one symbol (repeatable). Example: -s NVDA -s AAPL",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output folder for .ts files (default: ./tos_output next to this program)",
    )
    ap.add_argument(
        "--input",
        type=Path,
        metavar="FILE.csv",
        help="CSV exported from your spreadsheet (see README). Overrides built-in data.",
    )
    ap.add_argument(
        "--input-dir",
        type=Path,
        metavar="DIR",
        help="Folder of SYMBOL.csv files; generates one .ts per file.",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="List built-in MarkTen symbols and exit",
    )
    args = ap.parse_args(argv)

    if args.list:
        print("Built-in MarkTen symbols (use without --input):")
        for sym in MARKTEN:
            print(f"  {sym}")
        print("\nCustom data: export a CSV per symbol (see TOS_Zones_Generator_README.txt).")
        return 0

    if args.output is not None:
        out = Path(args.output).resolve()
    elif getattr(sys, "frozen", False):
        out = Path(sys.executable).resolve().parent / "tos_output"
    else:
        out = Path.cwd() / "tos_output"

    out.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {out}\n")

    errors = 0

    if args.input is not None:
        try:
            generate_from_csv(args.input, out, symbol=(args.symbols[0] if args.symbols else None))
            print()
        except Exception as exc:
            errors += 1
            print(f"ERROR: {exc}", file=sys.stderr)
    elif args.input_dir is not None:
        csv_files = sorted(Path(args.input_dir).glob("*.csv"))
        if not csv_files:
            print(f"No .csv files in {args.input_dir}", file=sys.stderr)
            return 1
        for path in csv_files:
            try:
                generate_from_csv(path, out)
                print()
            except Exception as exc:
                errors += 1
                print(f"ERROR {path.name}: {exc}", file=sys.stderr)
    elif args.all:
        for sym in MARKTEN:
            try:
                generate_symbol(sym, out)
                print()
            except Exception as exc:
                errors += 1
                print(f"ERROR {sym}: {exc}", file=sys.stderr)
    elif args.symbols:
        for sym in args.symbols:
            try:
                generate_symbol(sym, out)
                print()
            except Exception as exc:
                errors += 1
                print(f"ERROR {sym}: {exc}", file=sys.stderr)
    else:
        ap.print_help()
        print("\nTip: --all  |  -s NVDA  |  --input NFLX.csv")
        return 1

    if errors:
        return 1
    print("Done. Paste each SYMBOL_zones_trades.ts into ThinkorSwim Studies -> Create.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
