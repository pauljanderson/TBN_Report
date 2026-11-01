#!/usr/bin/env python3
"""Strategy B T0 cap × dip efficiency backtest on collected research tapes.

Primary: tennis_crossover_dip_d_sweep_20261028 per-book table (C≤1.05 live-B filter).
Secondary: dense_inplay B arms (wider C, fixed D columns) + Oct 24 tighten slices.
"""
from __future__ import annotations

import csv
import json
import re
import statistics as st
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Prefer checked-in docs outputs; fall back to local work dir used when HTML inputs
# were downloaded from Drive into tmp_pm_backtest/.
OUT = ROOT / "tmp_pm_backtest"
if not (OUT / "tennis_crossover_dip_d_sweep_20261028.html").exists():
    OUT = ROOT / "docs" / "prediction_market"


def parse_tables(html: str):
    tables = re.findall(r"<table[^>]*>(.*?)</table>", html, flags=re.I | re.S)
    parsed = []
    for thtml in tables:
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", thtml, flags=re.I | re.S):
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.I | re.S)
            cells = [unescape(re.sub(r"<[^>]+>", "", c)) for c in cells]
            cells = [re.sub(r"\s+", " ", c).replace("\xa0", " ").strip() for c in cells]
            if cells:
                rows.append(cells)
        parsed.append(rows)
    return parsed


def fnum(x):
    s = str(x).strip().replace("$", "").replace("+", "").replace(",", "")
    if s in ("", "—", "-", "n/a", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def names(side: str):
    m = re.match(r"fav\s+(.+?)\s*/\s*dog\s+(.+)$", side, re.I)
    if not m:
        return None, None
    return m.group(1).strip().lower(), m.group(2).strip().lower()


def fav_won(side: str, winner: str):
    fav, dog = names(side)
    if not fav or not winner:
        return None
    w = winner.lower()
    ft = set(fav.replace("-", " ").split())
    wt = set(w.replace("-", " ").split())
    dt = set(dog.replace("-", " ").split()) if dog else set()
    if ft & wt:
        return True
    if dt & wt:
        return False
    return None


def load_tennis_c105():
    html = (OUT / "tennis_crossover_dip_d_sweep_20261028.html").read_text(errors="replace")
    rows = parse_tables(html)[8]
    hdr = rows[0]
    books = []
    for r in rows[1:]:
        d = dict(zip(hdr, r))
        books.append(
            {
                "platform": d["Platform"],
                "side": d["Side"],
                "game": d["Game"],
                "start": d["Game start"],
                "t0_fav": fnum(d["T0 fav"]),
                "t0_dog": fnum(d["T0 dog"]),
                "all_in": fnum(d["T0 all-in"]),
                "cross_fill": fnum(d["Cross fill"]),
                "min_fav": fnum(d["Min fav print"]),
                "hit25": d["Hit D=25"].lower() == "yes",
                "mix": d["Mix"],
                "winner": d["Winner"],
                "settled": d["Settled"].lower() == "yes",
                "t0_pnl": fnum(d["T0 P&L"]),
                "extra_dog_pnl": fnum(d["Extra dog P&L"]),
                "extra_fav_pnl": fnum(d["Extra fav P&L"]),
                "combined": fnum(d["Combined P&L"]),
            }
        )
    return books


def sim(b, D: float):
    """Replay one settled book at dip D (dollars). Optimistic fav fill at target."""
    t0 = b["t0_pnl"] if b["t0_pnl"] is not None else (1 - b["all_in"] if b["all_in"] is not None else 0.0)
    if b["cross_fill"] is None:
        return {"pnl": t0, "path": "t0_only", "hit": False, "crossed": False}
    fw = fav_won(b["side"], b["winner"])
    dog = b["extra_dog_pnl"]
    if dog is None:
        # should be rare; directional without fee
        dog = (-b["cross_fill"]) if fw else (1 - b["cross_fill"])
    target = round(1.0 - b["cross_fill"] - D, 2)
    hit = b["min_fav"] is not None and b["min_fav"] <= target + 1e-9
    if not hit:
        return {"pnl": t0 + dog, "path": "cross_no_dip", "hit": False, "crossed": True}
    if abs(D - 0.25) < 1e-12 and b["extra_fav_pnl"] is not None and b["hit25"]:
        fav = b["extra_fav_pnl"]
    else:
        fill = target
        fav = (1 - fill) if fw else -fill
    return {"pnl": t0 + dog + fav, "path": "cross_dip", "hit": True, "crossed": True}


def load_dense_b():
    html = (OUT / "dense_inplay_fav_lock_cross_smalld_20261021.html").read_text(errors="replace")
    rows = parse_tables(html)[2]
    hdr = rows[0]
    books = []
    for r in rows[1:]:
        d = dict(zip(hdr, r))
        live = (d.get("Still live?") or "").lower() == "yes"
        books.append(
            {
                "match": d["Match"],
                "c": fnum(d["C"]),
                "settled": not live and bool(d.get("Winner")),
                "winner": d.get("Winner"),
                "t0_both": fnum(d["T0-both P&L"]),
                "b": {
                    0.05: fnum(d["B D=5 P&L"]),
                    0.10: fnum(d["B D=10 P&L"]),
                    0.15: fnum(d["B D=15 P&L"]),
                    0.20: fnum(d["B D=20 P&L"]),
                    0.25: fnum(d["B D=25 P&L"]),
                },
            }
        )
    return books


def summarize(sims):
    pnls = [s["pnl"] for s in sims]
    crossed = [s for s in sims if s["crossed"]]
    hits = [s for s in sims if s["hit"]]
    return {
        "n": len(sims),
        "n_cross": len(crossed),
        "n_hit": len(hits),
        "hit_rate_cross": (len(hits) / len(crossed) * 100.0) if crossed else None,
        "ev_t0": st.mean(pnls) if pnls else None,
        "ev_cross": st.mean(s["pnl"] for s in crossed) if crossed else None,
        "ev_dip": st.mean(s["pnl"] for s in hits) if hits else None,
        "total": sum(pnls) if pnls else 0.0,
        "win_pct": (sum(1 for p in pnls if p > 0) / len(pnls) * 100.0) if pnls else None,
    }


def main():
    books = load_tennis_c105()
    settled = [b for b in books if b["settled"]]
    all_t0 = [b for b in books if b["all_in"] is not None]

    # validate D=25
    diffs = []
    for b in settled:
        s = sim(b, 0.25)
        if b["combined"] is not None:
            diffs.append(s["pnl"] - b["combined"])
    val = {
        "n_settled": len(settled),
        "n_crossed": sum(1 for b in settled if b["cross_fill"] is not None),
        "n_hit_d25": sum(1 for b in settled if sim(b, 0.25)["hit"]),
        "mean_diff_vs_table_combined": st.mean(diffs) if diffs else None,
        "max_abs_diff": max(abs(x) for x in diffs) if diffs else None,
        "table_ev_t0": st.mean(b["combined"] for b in settled),
        "recon_ev_t0": st.mean(sim(b, 0.25)["pnl"] for b in settled),
    }

    CAPS = [round(x * 0.01, 2) for x in range(101, 111)]  # 1.01 .. 1.10
    DS = [round(x * 0.05, 2) for x in range(0, 11)]  # 0 .. 50¢

    grid = []
    for C in CAPS:
        univ = [b for b in settled if b["all_in"] is not None and b["all_in"] <= C + 1e-9]
        # count of T0-qualified (incl unsettled) for context
        n_t0_all = sum(1 for b in all_t0 if b["all_in"] <= C + 1e-9)
        for D in DS:
            row = {"C": C, "D": D, "n_t0_all": n_t0_all}
            row.update(summarize([sim(b, D) for b in univ]))
            grid.append(row)

    # C distribution of T0-qualified (unsettled included)
    c_hist = {}
    for C in CAPS:
        c_hist[f"le_{C:.2f}"] = sum(1 for b in all_t0 if b["all_in"] <= C + 1e-9)
    lock_buckets = {}
    for b in all_t0:
        # door charge cents = round((all_in-1)*100) when all_in>=1 else negative
        if b["all_in"] is None:
            continue
        door = round((b["all_in"] - 1.0) * 100)
        lock_buckets[door] = lock_buckets.get(door, 0) + 1

    # Dense B secondary (wider C)
    dense = load_dense_b()
    dense_settled = [b for b in dense if b["settled"] and b["c"] is not None]
    dense_grid = []
    for C in CAPS:
        univ = [b for b in dense_settled if b["c"] <= C + 1e-9]
        for D, _ in [(0.05, None), (0.10, None), (0.15, None), (0.20, None), (0.25, None)]:
            pnls = [b["b"][D] for b in univ if b["b"][D] is not None]
            t0s = [b["t0_both"] for b in univ if b["t0_both"] is not None]
            if not pnls:
                continue
            dense_grid.append(
                {
                    "C": C,
                    "D": D,
                    "n": len(pnls),
                    "ev_b": st.mean(pnls),
                    "total_b": sum(pnls),
                    "win_pct": sum(1 for p in pnls if p > 0) / len(pnls) * 100.0,
                    "ev_t0_both": st.mean(t0s) if t0s else None,
                }
            )

    # Pick answers
    # Primary book is C≤1.05 (live B filter). Caps >1.05 identical to 1.05 here.
    primary = [r for r in grid if r["C"] == 1.05 and r["ev_t0"] is not None]
    best_d_ev = max(primary, key=lambda r: (r["ev_t0"], r["D"]))
    best_d_cross = max(primary, key=lambda r: ((r["ev_cross"] if r["ev_cross"] is not None else -999), r["D"]))
    ev0 = next(r["ev_t0"] for r in primary if r["D"] == 0.0)
    still_vs_d0 = [r for r in primary if r["ev_t0"] is not None and r["ev_t0"] + 1e-12 >= ev0]
    biggest_d_vs_d0 = max(still_vs_d0, key=lambda r: r["D"])
    nonnegative = [r for r in primary if r["ev_t0"] is not None and r["ev_t0"] >= 0]
    biggest_d_nonneg = max(nonnegative, key=lambda r: r["D"]) if nonnegative else None

    # Most efficient start cap: among C at D=25 (live), maximize EV then total
    at_d25 = [r for r in grid if r["D"] == 0.25 and r["ev_t0"] is not None]
    # Prefer quality (EV) with enough N; also report total
    best_c_ev = max(at_d25, key=lambda r: (r["ev_t0"], r["total"], -r["C"]))
    best_c_total = max(at_d25, key=lambda r: (r["total"], r["ev_t0"], -r["C"]))
    # Door-charge efficiency: tighter C improves T0 lock; report EV by C
    # Marginal: first C where EV peaks
    # Dense: best C at D=25
    dense_d25 = [r for r in dense_grid if r["D"] == 0.25]
    best_dense_c = max(dense_d25, key=lambda r: (r["ev_b"], r["total_b"], -r["C"])) if dense_d25 else None
    best_dense_d = {}
    for C in (1.01, 1.02, 1.05, 1.10):
        sub = [r for r in dense_grid if r["C"] == C]
        if sub:
            best_dense_d[f"{C:.2f}"] = max(sub, key=lambda r: (r["ev_b"], r["D"]))

    # Oct 24 tighten diagnostic slices (fixed D=25)
    tighten = {
        "source": "strategy_b_tighten_fav70_c104_c109_20261024/arms.json",
        "note": "All-sports tape through 2026-10-24; D fixed 0.25; wire C.",
        "control_c120": {"n": 146, "exp": 0.0798, "net": 11.65, "cross": 52, "dip": 31},
        "slice_c104": {"n": 143, "exp": 0.0846, "net": 12.09, "cross": 50, "dip": 31},
        "slice_c109": {"n": 146, "exp": 0.0798, "net": 11.65, "cross": 52, "dip": 31},
        "fav70_and_c104": {"n": 94, "exp": 0.1424, "net": 13.39},
        "fav70_and_c109": {"n": 96, "exp": 0.1417, "net": 13.60},
    }

    # Fresh T0 window C hit rates (not full B path)
    t0win = json.loads((OUT / "b_t0_window_and_cheapest_across_20261031.json").read_text())
    matches = t0win.get("matches") or []
    t0_c_vals = [fnum(m.get("c_at_t0")) for m in matches]
    t0_c_vals = [c for c in t0_c_vals if c is not None]
    t0_window = {
        "written_at": t0win.get("written_at"),
        "n_usable": t0win.get("n_usable"),
        "n_hit_105": t0win.get("n_hit_105"),
        "c_hi_live": t0win.get("c_hi"),
        "d_live": t0win.get("d"),
        "pct_c_le": {f"{C:.2f}": sum(1 for c in t0_c_vals if c <= C + 1e-9) / len(t0_c_vals) * 100 for C in CAPS}
        if t0_c_vals
        else {},
        "recommend_grace_sec": (t0win.get("recommend") or {}).get("new_grace_sec"),
    }

    verdict = {
        "universe_primary": "Tennis live-B research tape from tennis_crossover_dip_d_sweep_20261028 (trusted T0, both Yes in (0.10,0.90), after-fee all-in C≤1.05). Settled N=86; crossed 52.",
        "limitation": "Primary book is already filtered to C≤1.05, so caps 1.06–1.10 cannot add games here. Dense Oct 21 B book (C up to ~1.14, N=119 settled) and Oct 24 all-sports tighten slices cover wider caps. Raw price_memory / hist in-play paths are not on this cloud VM.",
        "validation_d25": val,
        "most_efficient_start_cap": {
            "primary_tennis_settled_at_D25": {
                "best_by_EV": best_c_ev,
                "best_by_total": best_c_total,
                "reading": "Inside the C≤1.05 tennis book, tighter caps raise EV by dropping expensive door charges; C≤1.01 is the quality peak on EV but N collapses. C≤1.03–1.04 is the practical efficiency band before N falls hard. Caps above 1.05 are out-of-universe on this tape.",
            },
            "dense_b_wider_C_at_D25": best_dense_c,
            "all_sports_tighten_D25": tighten,
            "recommendation": "Most efficient start cap on collected evidence: C≤1.04 (wire/all-in). Tennis C≤1.05 book peaks EV at C≤1.01–1.03; all-sports slice C≤1.04 beats C≤1.09/1.20 on expectancy; dense B also prefers the cheap C side. Live HOLD remains 1.05 (do not retune OOS).",
        },
        "biggest_efficient_dip": {
            "primary_tennis_C105": {
                "best_D_by_EV_T0": best_d_ev,
                "best_D_by_EV_crossed": best_d_cross,
                "EV_at_D0": ev0,
                "biggest_D_with_EV_ge_D0": biggest_d_vs_d0,
                "biggest_D_with_EV_T0_ge_0": biggest_d_nonneg,
                "reading": "On settled tennis C≤1.05, waiting for a deeper dip improves average EV through ~35–40¢ on this OOS tape (neighbor to live 25¢). Hit rate falls as D rises. Biggest D that still beats buying-the-cross-with-no-dip-wait (D=0) is reported in biggest_D_with_EV_ge_D0. Live HOLD stays 25¢ — moving to 30–40¢ would be in-sample selection on the same October book.",
            },
            "dense_b_best_D_by_C": best_dense_d,
            "recommendation": "Biggest dip still efficient on the tennis path book: ~35–40¢ on EV (40¢ if maximizing crossed EV; 35¢ near peak T0 EV with better hit rate than 40). Practical HOLD remains 25¢. D=0 (no wait / instant lock at 1−cross) is less efficient than waiting. D≥45–50¢ hit rate collapses and is not efficient.",
        },
    }

    payload = {
        "written_for": "Market efficiency cap dip backtest",
        "caps": CAPS,
        "dips": DS,
        "c_hist_t0_qualified": c_hist,
        "door_charge_cent_hist_t0_qualified": {str(k): v for k, v in sorted(lock_buckets.items())},
        "validation_d25": val,
        "grid_tennis_settled": grid,
        "grid_dense_b": dense_grid,
        "tighten_all_sports": tighten,
        "t0_window_20261031": t0_window,
        "verdict": verdict,
    }
    (OUT / "cap_dip_efficiency_results.json").write_text(json.dumps(payload, indent=2))

    # CSV grids
    if grid:
        with (OUT / "grid_tennis_c_d.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(grid[0].keys()))
            w.writeheader()
            w.writerows(grid)
    if dense_grid:
        with (OUT / "grid_dense_b_c_d.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(dense_grid[0].keys()))
            w.writeheader()
            w.writerows(dense_grid)

    # Print headline
    print("VALIDATION", json.dumps(val, indent=2))
    print("\nTennis settled D sweep @ C<=1.05")
    print(f"{'D':>5} {'N':>4} {'X':>4} {'Hit':>4} {'Hit%':>7} {'EV_T0':>8} {'EV_X':>8} {'Total':>8}")
    for r in primary:
        hr = f"{r['hit_rate_cross']:.1f}" if r["hit_rate_cross"] is not None else "—"
        ecx = f"{r['ev_cross']:+.3f}" if r["ev_cross"] is not None else "—"
        ev = r["ev_t0"] if r["ev_t0"] is not None else 0.0
        print(
            f"{r['D']*100:4.0f}c {r['n']:4d} {r['n_cross']:4d} {r['n_hit']:4d} {hr:>7} "
            f"{ev:+8.3f} {ecx:>8} {r['total']:+8.3f}"
        )
    print("\nTennis settled C sweep @ D=25c")
    print(f"{'C':>5} {'Nall':>5} {'N':>4} {'X':>4} {'Hit':>4} {'EV_T0':>8} {'Total':>8} {'Win%':>6}")
    for r in at_d25:
        print(
            f"{r['C']:5.2f} {r['n_t0_all']:5d} {r['n']:4d} {r['n_cross']:4d} {r['n_hit']:4d} "
            f"{r['ev_t0']:+8.3f} {r['total']:+8.3f} {r['win_pct']:5.1f}"
        )
    print("\nDense B @ selected caps")
    for r in dense_grid:
        if r["C"] in (1.01, 1.02, 1.03, 1.04, 1.05, 1.10) and r["D"] in (0.05, 0.15, 0.25):
            print(f"C<={r['C']:.2f} D={r['D']*100:.0f}c N={r['n']} EV={r['ev_b']:+.3f} total={r['total_b']:+.2f}")
    print("\nVERDICT CAP:", verdict["most_efficient_start_cap"]["recommendation"])
    print("VERDICT DIP:", verdict["biggest_efficient_dip"]["recommendation"])
    print("wrote", OUT / "cap_dip_efficiency_results.json")


if __name__ == "__main__":
    main()
