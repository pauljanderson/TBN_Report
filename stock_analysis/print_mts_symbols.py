"""Print MTS_SYMBOLS_CSV to stdout (for run_mts.bat; avoids fragile for /f quoting)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mts_universe import MTS_SYMBOLS_CSV

print(MTS_SYMBOLS_CSV, end="")
