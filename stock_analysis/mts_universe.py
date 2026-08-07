"""Official MTS backtest universe (MTS_Optimizer, generate_investment_report).

SSoT: drive/universes/MTS_universe.csv (one ticker per line; also used by run_mts.bat).
Falls back to a hardcoded list if the CSV is missing.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CSV_PATH = _REPO_ROOT / "drive" / "universes" / "MTS_universe.csv"

_FALLBACK = [
    "AAON", "ABCB", "ABG", "ACA", "ACU", "ALG", "AMD", "AMN", "APP", "ARES",
    "ATEYY", "AU", "BBW", "BELFA", "BWLP", "CF", "CHCI", "CIEN", "CLS", "CMC",
    "COHR", "COKE", "CRS", "CRWD", "CSTM", "CVCO", "DDS", "DECK", "DKL", "DKS",
    "DXCM", "DY", "ENVA", "ESP", "EVR", "FEIM", "FN", "FRD", "FTAI", "HWKN",
    "IBP", "IESC", "IR", "JOE", "LMAT", "LOGI", "LRCX", "LUGDF", "LULU", "MATX",
    "MOD", "MPWR", "MTSI", "MTZ", "MYRG", "NEO", "NGL", "NTAP", "NVDA", "NVMI",
    "NXPI", "OR", "PFSI", "PLUS", "POOL", "POWL", "PTC", "QXO", "RMBS", "SANM",
    "SCCO", "SGI", "SHOP", "SIMO", "SKYW", "TATT", "TBBK", "TER", "TOELY", "TPH",
    "TRT", "TWLO", "UHS", "URI", "UTI", "VSEC", "WDAY", "WOR", "XPO",
]


def _load_from_csv(path: Path) -> list[str] | None:
    if not path.is_file():
        return None
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        for part in line.replace(";", ",").split(","):
            tok = part.strip().strip('"').strip("'").upper()
            if tok and tok not in ("*", "ALL"):
                out.append(tok)
    return out or None


MTS_SYMBOLS = _load_from_csv(_CSV_PATH) or list(_FALLBACK)
MTS_SYMBOLS_CSV = ",".join(MTS_SYMBOLS)
