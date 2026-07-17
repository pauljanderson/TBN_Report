"""Find DB_Closed_*.csv file with highest average PNL %."""

import csv
from pathlib import Path

DRIVE_DIR = Path(r"C:\Users\songg\Downloads\stockresearch\Drive")
PNL_COLUMN_INDEX = 6  # 7th column (0-based)


def parse_pnl(value: str) -> float | None:
    """Parse PNL % value (e.g. '-4.02%' or '10.00%') to float."""
    value = value.strip().rstrip("%").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def process_file(filepath: Path) -> tuple[float, int] | None:
    """Return (sum, count) of PNL values, or None if no valid rows."""
    total = 0.0
    count = 0
    with open(filepath, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) <= PNL_COLUMN_INDEX:
                continue
            pnl = parse_pnl(row[PNL_COLUMN_INDEX])
            if pnl is not None:
                total += pnl
                count += 1
    return (total, count) if count > 0 else None


def main() -> None:
    files = sorted(DRIVE_DIR.glob("DB_Closed_*.csv"))
    if not files:
        print("No DB_Closed_*.csv files found.")
        return

    best_file: Path | None = None
    best_avg: float | None = None

    for filepath in files:
        result = process_file(filepath)
        if result is None:
            continue
        total, count = result
        avg = total / count
        if best_avg is None or avg > best_avg:
            best_avg = avg
            best_file = filepath

    if best_file is None or best_avg is None:
        print("No valid PNL data found in any file.")
        return

    print(f"File with highest average PNL %: {best_file.name}")
    print(f"Average PNL %: {best_avg:.2f}%")


if __name__ == "__main__":
    main()
