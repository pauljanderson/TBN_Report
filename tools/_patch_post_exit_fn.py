from pathlib import Path

p = Path(__file__).resolve().parents[1] / "stock_analysis" / "rocket_rl.py"
text = p.read_text(encoding="utf-8")
marker = "def _fmt_opt_float(v: Optional[float], places: int = 2) -> str:"
if "def compute_post_exit_path(" in text:
    print("already present")
    raise SystemExit(0)
fn = '''
def compute_post_exit_path(
    *,
    highs: np.ndarray,
    closes: np.ndarray,
    exit_idx: int,
    exit_price: float,
    pnl_days: tuple[int, ...] = PNL_AFTER_EXIT_DAYS,
    max_gain_days: tuple[int, ...] = MAX_GAIN_AFTER_EXIT_DAYS,
) -> tuple[dict[int, Optional[float]], dict[int, Optional[float]]]:
    """PnL% and MAX_GAIN path after exit (exit bar = day 0), vs exit price.

    PNL_XD_AFTER_EXIT = (close_at_exit+X − exit) / exit × 100
    MAX_GAIN_XD_AFTER_EXIT = (max High exit..exit+X − exit) / exit
    Insufficient bars -> None (blank in CSV).
    """
    n = len(highs)
    pnl: dict[int, Optional[float]] = {}
    mxg: dict[int, Optional[float]] = {}
    for d in pnl_days:
        tgt = exit_idx + d
        if tgt >= n:
            pnl[d] = None
            continue
        px = float(closes[tgt])
        pnl[d] = (px - exit_price) / exit_price * 100.0 if exit_price > 0 else 0.0
    for d in max_gain_days:
        tgt = exit_idx + d
        if tgt >= n:
            mxg[d] = None
            continue
        mx = float(np.max(highs[exit_idx : tgt + 1]))
        mxg[d] = (mx - exit_price) / exit_price if exit_price > 0 else 0.0
    return pnl, mxg


'''
idx = text.find(marker)
if idx < 0:
    raise SystemExit("marker not found")
p.write_text(text[:idx] + fn + text[idx:], encoding="utf-8")
print("inserted compute_post_exit_path")
