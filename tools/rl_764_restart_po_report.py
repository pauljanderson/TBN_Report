#!/usr/bin/env python3
"""PO master report: RL 764 tradable restart (2026-08-28).

Writes drive/paul_experiments/rl_764_restart_po_report_20260828.html
"""
from __future__ import annotations

import html as html_mod
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "drive" / "paul_experiments" / "rl_764_restart_po_report_20260828.html"

sys.path.insert(0, str(ROOT / "tools"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, sortable_th  # noqa: E402


def esc(s: object) -> str:
    return html_mod.escape("" if s is None else str(s))


def ths(cols: list[tuple[str, str]]) -> str:
    return "".join(sortable_th(a, b) for a, b in cols)


def tr(cells: list[str], *, cls: str = "") -> str:
    attr = f' class="{cls}"' if cls else ""
    tds = "".join(f"<td>{c}</td>" for c in cells)
    return f"<tr{attr}>{tds}</tr>"


def main() -> int:
    m_cols = [
        ("Arm", "text"),
        ("Split", "text"),
        ("N", "num"),
        ("WR%", "num"),
        ("Avg PnL%", "num"),
        ("WO_MAX%", "num"),
        ("Avg win%", "num"),
        ("Avg loss%", "num"),
        ("PF", "num"),
        ("Ann ROR%", "num"),
        ("Calmar (overlay)", "num"),
        ("Overlay Max DD%", "num"),
        ("Host Max DD%", "num"),
        ("Avg days", "num"),
        ("Trades/yr", "num"),
    ]

    def mrow(*vals: object, cls: str = "") -> str:
        cells = [esc(v) for v in vals]
        return tr(cells, cls=cls)

    dec_cols = [
        ("#", "num"),
        ("Stamp", "text"),
        ("Knob (one change)", "text"),
        ("Side", "text"),
        ("Arms vs freeze", "text"),
        ("House IS", "text"),
        ("House OOS", "text"),
        ("PO call", "text"),
        ("Compare", "text"),
    ]
    decisions = [
        tr(
            [
                "0",
                "<code>rl_tradable_2010_adv2m_20260828</code>",
                "Universe identity (not a param)",
                "UNIV",
                "764 tradable vs house 59 vs List2",
                "764 DISMISS vs 59 (expected)",
                "764 DISMISS vs 59 (59 is a whitelist)",
                "<strong>KEEP research tape</strong> — 764 is the honest from-scratch book",
                '<a href="rl_tradable_2010_adv2m_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "0b",
                "<code>rl_univ_compare_paul8_paul78_20260828</code>",
                "Paul8 / Paul78 IS winner-cuts vs List2",
                "UNIV",
                "List1/2, Paul8 (56), Paul78 (102), house 59",
                "LEAN KEEP vs 59 (circular on Paul arms)",
                "vs List2: Paul8 LEAN KEEP; Paul78 HOLD",
                "<strong>HOLD only</strong> — still a winner-cut, not gold, not the 764 hunt",
                '<a href="rl_univ_compare_paul8_paul78_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "1",
                "<code>rl_be_trail_tradable_20260828</code>",
                "<code>rl_trail_profit</code> break-even after +14% / +20%",
                "EXIT",
                "off; 10% (prior dismiss); 14%; 20%",
                "DISMISS",
                "DISMISS (OOS Avg/WR down)",
                "<strong>DISMISS</strong>",
                '<a href="rl_be_trail_tradable_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "2",
                "<code>rl_post_target_reentry_tradable_20260828</code>",
                "<code>rl_post_target_reentry_bars</code> mode=none",
                "ENTRY",
                "0; 10; 15",
                "DISMISS both",
                "HOLD (flat)",
                "<strong>DISMISS</strong>",
                '<a href="rl_post_target_reentry_tradable_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "3",
                "<code>rl_stop_expand_tradable_20260828</code>",
                "<code>rl_stop_pct</code> expand",
                "EXIT",
                "0.934; 0.92; 0.90",
                "0.92 DISMISS (overlay DD); 0.90 LEAN KEEP",
                "0.90 LEAN KEEP report-only",
                "<strong>DISMISS</strong> — IS Ann ROR 16.4→15.0 (104→141d book)",
                '<a href="rl_stop_expand_tradable_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "4",
                "<code>rl_target_expand_tradable_20260828</code>",
                "<code>rl_target_pct</code> expand",
                "EXIT",
                "1.20; 1.25; 1.30",
                "DISMISS (WR / overlay DD collapse)",
                "DISMISS (Ann ROR 31.7→27.8 / 23.0)",
                "<strong>DISMISS</strong> — host DD 17.7→36.5 / 55.3",
                '<a href="rl_target_expand_tradable_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "5",
                "<code>rl_partial_exit_tradable_20260828</code>",
                "50% at +20%, remainder ×1.30",
                "EXIT",
                "off vs one frozen recipe",
                "DISMISS Avg 4.42→3.74",
                "DISMISS Ann ROR 31.7→27.8",
                "<strong>DISMISS</strong> — IS recycle looked better; OOS veto",
                '<a href="rl_partial_exit_tradable_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "6",
                "<code>rl_scale_ladder_tradable_20260828</code>",
                "Scale-out + stop ratchet",
                "EXIT",
                "off; two-step; three-step",
                "DISMISS Avg 4.42→2.46 / 2.51",
                "DISMISS Avg 3.77→1.81 / 1.84",
                "<strong>DISMISS</strong> — WR up, avg win ~29→12",
                '<a href="rl_scale_ladder_tradable_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "7",
                "<code>rl_dip_tighten_tradable_20260828</code>",
                "<code>rl_dip_pct</code> tighten",
                "ENTRY",
                "1.055; 1.041; 1.030",
                "1.041 HOLD; 1.030 DISMISS",
                "1.041 HOLD; 1.030 LEAN KEEP (do not retune OOS)",
                "<strong>HOLD 1.041 / DISMISS 1.030</strong> — freeze stays 1.055 (N −27% at 1.041)",
                '<a href="rl_dip_tighten_tradable_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "8",
                "<code>rl_stop_tighten_tradable_20260828</code>",
                "<code>rl_stop_pct</code> tighten",
                "EXIT",
                "0.934; 0.940; 0.945",
                "DISMISS Avg 4.42→4.14",
                "DISMISS",
                "<strong>DISMISS</strong>",
                '<a href="rl_stop_tighten_tradable_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "9",
                "<code>rl_target_contract_tradable_20260828</code>",
                "<code>rl_target_pct</code> contract",
                "EXIT",
                "1.20; 1.18; 1.15",
                "DISMISS on Avg",
                "DISMISS Ann ROR 31.7→25.8 / 25.6",
                "<strong>1.15 no. 1.18 weaker CONSIDER</strong> — IS recycle yes; OOS softened. Freeze 1.20",
                '<a href="rl_target_contract_tradable_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "10",
                "<code>rl_slope_gate_tradable_20260828</code>",
                "<code>rl_slope_threshold</code>",
                "ENTRY",
                "0; 0.05; 0.0643",
                "0.05 LEAN KEEP; 0.0643 DISMISS",
                "0.05 HOLD; 0.0643 DISMISS",
                "<strong>PO DISMISS both</strong> — tiny IS lift; OOS/host DD not better. Freeze 0",
                '<a href="rl_slope_gate_tradable_20260828/compare.html">html</a>',
            ]
        ),
        tr(
            [
                "11",
                "<code>rl_time_stop_tradable_20260828</code>",
                "<code>rl_exit_days</code> after +29% mark-to-market",
                "EXIT",
                "10000 (off); 40; 80",
                "DISMISS Avg (house rule)",
                "HOLD (Avg flat; Ann ROR up)",
                "<strong>PO CONSIDER 40d</strong> (not 80). Freeze still 10000 until adopt. First print VOID (fill bug)",
                '<a href="rl_time_stop_tradable_20260828/compare.html">html</a>',
            ],
            cls="hi-row",
        ),
        tr(
            [
                "12",
                "<code>rl_time_stop_40_wf_tradable_20260828</code>",
                "Walk-forward locked 40 vs off",
                "EXIT",
                "No new knob; 3y train / 1y test",
                "n/a (fold report)",
                "9/14 folds 40d Ann ROR win",
                "<strong>CONSIDER survives WF</strong> — not gold. Lost 2014 / 2018 / 2022 / 2023",
                '<a href="rl_time_stop_40_wf_tradable_20260828/compare.html">html</a>',
            ],
            cls="hi-row",
        ),
    ]

    univ_rows = [
        mrow("Tradable 764", "IS", "1726", "37.0", "4.42", "4.08", "29.3", "−10.2", "1.69", "16.37", "0.43", "37.74", "17.72", "104", "113", cls="ctrl-row"),
        mrow("List2 (93, IS cut)", "IS", "715", "56.6", "9.32", "8.98", "—", "—", "3.15", "83.72", "—", "7.42", "—", "—", "—"),
        mrow("House 59 whitelist", "IS", "430", "55.1", "8.24", "8.06", "—", "—", "2.83", "81.02", "—", "9.36", "—", "—", "—"),
        mrow("Tradable 764", "OOS", "630", "39.8", "3.77", "3.67", "24.1", "−9.8", "1.65", "31.72", "1.86", "17.09", "—", "49", "238", cls="ctrl-row"),
        mrow("List2 (93, IS cut)", "OOS", "242", "42.1", "2.96", "2.66", "—", "—", "1.51", "44.12", "—", "11.33", "—", "—", "—"),
        mrow("House 59 whitelist", "OOS", "240", "60.0", "9.16", "8.89", "—", "—", "3.35", "201.89", "—", "3.98", "—", "—", "—"),
        mrow("Tradable 764", "FULL", "2356", "37.7", "4.25", "4.00", "27.8", "−10.1", "1.68", "18.51", "0.49", "37.74", "17.72", "89", "149", cls="ctrl-row"),
        mrow("List2 (93, IS cut)", "FULL", "957", "53.0", "7.71", "7.45", "—", "—", "2.64", "77.37", "—", "7.42", "—", "—", "—"),
        mrow("House 59 whitelist", "FULL", "670", "56.9", "8.57", "8.46", "—", "—", "3.00", "105.63", "—", "9.36", "—", "—", "—"),
    ]

    control_rows = [
        mrow("Control (764 freeze)", "IS", "1726", "37.0", "4.42", "4.08", "29.3", "−10.2", "1.69", "16.37", "0.43", "37.74", "17.72", "104", "113", cls="ctrl-row"),
        mrow("Control (764 freeze)", "OOS", "630", "39.8", "3.77", "3.67", "24.1", "−9.8", "1.65", "31.72", "1.86", "17.09", "—", "49", "238", cls="ctrl-row"),
        mrow("Control (764 freeze)", "FULL", "2356", "37.7", "4.25", "4.00", "27.8", "−10.1", "1.68", "18.51", "0.49", "37.74", "17.72", "89", "149", cls="ctrl-row"),
    ]

    # All one-knob arms, IS then OOS. Host DD is full-book EquityMeta (not split).
    all_arm_rows = [
        mrow("Control freeze", "IS", "1726", "37.0", "4.42", "4.08", "29.3", "−10.2", "1.69", "16.37", "0.43", "37.74", "17.72", "104", "113", cls="ctrl-row"),
        mrow("Control freeze", "OOS", "630", "39.8", "3.77", "3.67", "24.1", "−9.8", "1.65", "31.72", "1.86", "17.09", "—", "49", "238", cls="ctrl-row"),
        mrow("BE trail 14%", "FULL", "—", "31.6", "2.75", "—", "—", "—", "1.55", "—", "—", "34.23", "—", "—", "—"),
        mrow("BE trail 20%", "FULL", "—", "34.4", "3.44", "—", "—", "—", "1.62", "—", "—", "40.57", "—", "—", "—"),
        mrow("Reentry bars=10", "IS", "1662", "36.4", "4.24", "3.88", "—", "—", "1.66", "15.79", "—", "38.11", "—", "—", "—"),
        mrow("Reentry bars=10", "OOS", "595", "39.0", "3.77", "3.66", "—", "—", "1.64", "30.67", "—", "16.44", "—", "—", "—"),
        mrow("Reentry bars=15", "IS", "1606", "36.2", "4.22", "3.85", "—", "—", "1.65", "15.59", "—", "34.66", "—", "—", "—"),
        mrow("Reentry bars=15", "OOS", "568", "38.6", "3.75", "3.64", "—", "—", "1.64", "29.72", "—", "16.37", "—", "—", "—"),
        mrow("Stop 0.92", "IS", "1710", "39.8", "5.03", "4.68", "—", "—", "1.72", "15.67", "—", "42.85", "—", "—", "—"),
        mrow("Stop 0.92", "OOS", "618", "43.2", "4.12", "4.02", "—", "—", "1.65", "30.87", "—", "20.89", "—", "—", "—"),
        mrow("Stop 0.90", "IS", "1697", "43.3", "5.53", "5.18", "—", "−13.6", "1.72", "14.97", "—", "38.98", "—", "141", "—"),
        mrow("Stop 0.90", "OOS", "604", "48.2", "5.01", "4.86", "—", "—", "1.74", "33.20", "—", "18.36", "—", "—", "—"),
        mrow("Target 1.25", "IS", "1543", "27.3", "9.67", "7.67", "~63", "—", "2.29", "21.90", "—", "80.55", "36.5", "—", "—"),
        mrow("Target 1.25", "OOS", "534", "30.9", "4.19", "3.89", "—", "—", "1.61", "27.82", "—", "30.32", "—", "—", "—"),
        mrow("Target 1.30", "IS", "1386", "19.6", "11.24", "8.91", "~100", "—", "2.34", "20.31", "—", "131.63", "55.3", "—", "—"),
        mrow("Target 1.30", "OOS", "465", "22.2", "4.02", "3.53", "—", "—", "1.50", "23.01", "—", "59.17", "—", "—", "—"),
        mrow("Partial 50%/+20%", "IS", "1708", "45.8", "3.74", "3.71", "~20", "—", "1.68", "21.95", "—", "16.69", "7.16", "68", "—"),
        mrow("Partial 50%/+20%", "OOS", "611", "42.7", "3.24", "3.17", "—", "—", "1.58", "27.84", "—", "18.59", "—", "—", "—"),
        mrow("Ladder two-step", "IS", "1776", "57.7", "2.46", "2.38", "~12", "—", "1.58", "18.21", "—", "21.80", "9.96", "—", "—"),
        mrow("Ladder two-step", "OOS", "660", "56.1", "1.81", "1.76", "—", "—", "1.43", "23.25", "—", "16.13", "—", "—", "—"),
        mrow("Ladder three-step", "IS", "1777", "57.7", "2.51", "2.47", "~12", "—", "1.59", "19.54", "—", "18.88", "9.15", "—", "—"),
        mrow("Ladder three-step", "OOS", "662", "56.0", "1.84", "1.78", "—", "—", "1.44", "23.76", "—", "15.87", "—", "—", "—"),
        mrow("Dip 1.041", "IS", "1265", "36.4", "4.43", "4.22", "—", "—", "1.67", "16.67", "—", "38.47", "18.26", "—", "—"),
        mrow("Dip 1.041", "OOS", "498", "39.0", "3.67", "3.55", "—", "—", "1.62", "34.97", "—", "18.39", "—", "—", "—"),
        mrow("Dip 1.030", "IS", "958", "34.6", "3.70", "3.44", "—", "—", "1.54", "14.65", "—", "36.01", "19.14", "—", "—"),
        mrow("Dip 1.030", "OOS", "379", "41.4", "4.63", "4.48", "—", "—", "1.80", "47.37", "—", "13.32", "—", "—", "—"),
        mrow("Stop 0.940", "IS", "1737", "35.4", "4.14", "3.80", "—", "—", "1.67", "16.23", "—", "37.11", "17.76", "—", "—"),
        mrow("Stop 0.940", "OOS", "636", "38.5", "3.65", "3.55", "—", "—", "1.65", "31.14", "—", "17.27", "—", "—", "—"),
        mrow("Stop 0.945", "IS", "1745", "34.6", "4.14", "3.80", "—", "—", "1.70", "16.79", "—", "38.28", "17.38", "—", "—"),
        mrow("Stop 0.945", "OOS", "640", "36.4", "3.13", "3.03", "—", "—", "1.57", "28.12", "—", "16.93", "—", "—", "—"),
        mrow("Target 1.18", "IS", "1800", "41.2", "4.14", "3.64", "24.4", "−10.2", "1.70", "19.07", "0.50", "37.82", "15.10", "85", "114", cls="hi-row"),
        mrow("Target 1.18", "OOS", "657", "42.0", "2.71", "2.63", "19.6", "−9.7", "1.49", "25.77", "1.26", "20.48", "—", "43", "248", cls="hi-row"),
        mrow("Target 1.15", "IS", "1858", "49.7", "2.76", "2.47", "15.3", "−10.0", "1.57", "21.59", "0.99", "21.88", "7.10", "51", "132"),
        mrow("Target 1.15", "OOS", "690", "48.3", "2.00", "1.94", "13.7", "−9.4", "1.43", "25.58", "1.32", "19.38", "—", "32", "260"),
        mrow("Slope 0.05", "IS", "1651", "36.4", "4.54", "4.18", "—", "—", "1.70", "16.49", "—", "36.74", "18.26", "—", "—"),
        mrow("Slope 0.05", "OOS", "603", "39.5", "3.70", "3.59", "—", "—", "1.63", "31.48", "—", "17.40", "—", "—", "—"),
        mrow("Slope 0.0643", "IS", "1591", "36.3", "4.61", "4.23", "—", "—", "1.71", "16.71", "—", "42.18", "18.17", "—", "—"),
        mrow("Slope 0.0643", "OOS", "583", "39.3", "3.57", "3.46", "—", "—", "1.61", "30.74", "—", "17.27", "—", "—", "—"),
        mrow("Time-stop 40d (fill-fixed)", "IS", "1746", "41.1", "3.54", "3.51", "23.2", "−10.3", "1.59", "20.97", "0.77", "27.23", "7.79", "67", "129", cls="hi-row"),
        mrow("Time-stop 40d (fill-fixed)", "OOS", "636", "41.4", "3.74", "3.66", "22.8", "−9.8", "1.66", "34.13", "2.00", "17.09", "—", "46", "240", cls="hi-row"),
        mrow("Time-stop 80d (not pick)", "IS", "1743", "40.7", "3.67", "3.63", "23.9", "−10.3", "1.61", "20.27", "0.69", "29.34", "9.76", "71", "128"),
        mrow("Time-stop 80d (not pick)", "OOS", "634", "41.0", "3.73", "3.63", "23.0", "−9.8", "1.65", "32.59", "1.91", "17.09", "—", "47", "239"),
    ]

    consider_rows = [
        mrow("Control freeze", "IS", "1726", "37.0", "4.42", "4.08", "29.3", "−10.2", "1.69", "16.37", "0.43", "37.74", "17.72", "104", "113", cls="ctrl-row"),
        mrow("40d time-stop", "IS", "1746", "41.1", "3.54", "3.51", "23.2", "−10.3", "1.59", "20.97", "0.77", "27.23", "7.79", "67", "129", cls="hi-row"),
        mrow("Target 1.18", "IS", "1800", "41.2", "4.14", "3.64", "24.4", "−10.2", "1.70", "19.07", "0.50", "37.82", "15.10", "85", "114"),
        mrow("Control freeze", "OOS", "630", "39.8", "3.77", "3.67", "24.1", "−9.8", "1.65", "31.72", "1.86", "17.09", "—", "49", "238", cls="ctrl-row"),
        mrow("40d time-stop", "OOS", "636", "41.4", "3.74", "3.66", "22.8", "−9.8", "1.66", "34.13", "2.00", "17.09", "—", "46", "240", cls="hi-row"),
        mrow("Target 1.18", "OOS", "657", "42.0", "2.71", "2.63", "19.6", "−9.7", "1.49", "25.77", "1.26", "20.48", "—", "43", "248"),
        mrow("Control freeze", "FULL", "2356", "37.7", "4.25", "4.00", "27.8", "−10.1", "1.68", "18.51", "0.49", "37.74", "17.72", "89", "149", cls="ctrl-row"),
        mrow("40d time-stop", "FULL", "2382", "41.2", "3.59", "3.57", "23.1", "−10.2", "1.61", "23.49", "0.86", "27.23", "7.79", "61", "150", cls="hi-row"),
        mrow("Target 1.18", "FULL", "2457", "41.4", "3.75", "3.39", "23.1", "−10.1", "1.65", "20.09", "0.53", "37.82", "15.10", "73", "155"),
    ]

    fit_cols = [
        ("Arm (FULL book)", "text"),
        ("Mean Paul", "num"),
        ("Mean FIT", "num"),
        ("Mean robust FIT", "num"),
        ("Host Sharpe", "num"),
        ("Host Max DD%", "num"),
        ("Host max days UW", "num"),
        ("% days UW", "num"),
        ("Aggressive Max DD%", "num"),
    ]
    fit_rows = [
        tr([esc(c) for c in r], cls="ctrl-row")
        for r in [
            ("Control freeze", "3.60", "0.37", "−2.35", "0.32", "17.72", "694", "91.2", "45.04"),
        ]
    ] + [
        tr([esc(c) for c in r], cls="hi-row")
        for r in [
            ("40d time-stop", "3.78", "1.15", "−1.58", "0.41", "7.79", "646", "92.7", "39.64"),
        ]
    ] + [
        tr([esc(c) for c in ("Target 1.18", "3.53", "0.46", "−2.22", "0.27", "15.10", "—", "—", "—")])
    ]

    wf_cols = [
        ("Test year", "text"),
        ("N off", "num"),
        ("N 40d", "num"),
        ("WR% off", "num"),
        ("WR% 40d", "num"),
        ("Avg% off", "num"),
        ("Avg% 40d", "num"),
        ("PF off", "num"),
        ("PF 40d", "num"),
        ("Ann ROR% off", "num"),
        ("Ann ROR% 40d", "num"),
        ("Overlay DD% off", "num"),
        ("Overlay DD% 40d", "num"),
        ("Avg days off", "num"),
        ("Avg days 40d", "num"),
        ("40d AnnROR", "text"),
        ("40d DD", "text"),
    ]
    wf_folds = [
        ("2013", "132", "132", "40.2", "47.0", "10.60", "6.54", "2.86", "2.28", "19.98", "37.22", "16.84", "16.84", "202", "73", "yes", "tie"),
        ("2014", "86", "87", "24.4", "24.1", "2.83", "−1.19", "1.38", "0.84", "10.03", "−5.76", "21.96", "24.31", "107", "74", "no", "no"),
        ("2015", "74", "74", "25.7", "27.0", "−0.99", "−0.68", "0.86", "0.90", "−5.39", "−4.42", "25.92", "22.57", "65", "55", "yes", "yes"),
        ("2016", "100", "100", "46.0", "51.0", "6.37", "6.86", "2.13", "2.31", "26.87", "40.76", "17.56", "17.56", "95", "71", "yes", "tie"),
        ("2017", "67", "67", "38.8", "43.3", "5.31", "6.01", "1.98", "2.20", "21.97", "41.43", "7.51", "7.51", "95", "61", "yes", "tie"),
        ("2018", "90", "91", "23.3", "25.3", "−0.61", "−1.24", "0.92", "0.83", "−2.52", "−6.18", "24.45", "17.19", "87", "71", "no", "yes"),
        ("2019", "71", "71", "33.8", "36.6", "−0.74", "−0.29", "0.90", "0.96", "−5.12", "−2.08", "14.23", "14.06", "51", "50", "yes", "yes"),
        ("2020", "212", "220", "48.1", "58.2", "6.25", "9.86", "2.07", "3.12", "18.22", "56.09", "32.76", "32.76", "132", "77", "yes", "tie"),
        ("2021", "374", "376", "41.4", "46.8", "4.40", "4.56", "1.71", "1.80", "15.81", "24.12", "16.80", "13.24", "107", "75", "yes", "yes"),
        ("2022", "142", "146", "36.6", "37.0", "4.34", "2.43", "1.68", "1.38", "26.43", "20.16", "25.19", "21.23", "66", "48", "no", "yes"),
        ("2023", "105", "107", "30.5", "30.8", "1.74", "0.84", "1.26", "1.13", "10.32", "5.62", "31.61", "22.66", "64", "56", "no", "yes"),
        ("2024", "196", "198", "33.2", "36.9", "4.39", "4.27", "1.74", "1.77", "19.53", "22.34", "17.09", "17.09", "88", "76", "yes", "tie"),
        ("2025", "191", "194", "46.6", "47.4", "6.48", "6.33", "2.25", "2.24", "69.94", "67.02", "19.48", "18.98", "43", "44", "no", "yes"),
        ("2026 YTD", "243", "244", "39.9", "40.2", "1.13", "1.25", "1.18", "1.20", "20.34", "21.95", "40.81", "40.81", "22", "23", "yes", "tie"),
    ]
    wf_body = "".join(
        tr([esc(c) for c in row], cls="hi-row" if row[-2] == "yes" else "")
        for row in wf_folds
    )
    wf_pool_cols = [
        ("Sleeve", "text"),
        ("Trades", "num"),
        ("WR%", "num"),
        ("Avg PnL%", "num"),
        ("WO_MAX%", "num"),
        ("PF", "num"),
        ("Ann ROR%", "num"),
        ("Overlay Max DD%", "num"),
        ("Calmar", "num"),
        ("Avg days", "num"),
    ]
    wf_pool = [
        tr([esc(c) for c in ("Always off (test years)", "2083", "38.5", "4.13", "4.01", "1.67", "18.29", "17.33", "1.06", "87.9")], cls="ctrl-row"),
        tr([esc(c) for c in ("Always 40d (test years)", "2107", "42.1", "3.97", "3.95", "1.68", "26.23", "17.07", "1.54", "61.0")], cls="hi-row"),
        tr([esc(c) for c in ("Embargoed (train AnnROR pick)", "2103", "41.1", "4.35", "4.23", "1.73", "23.71", "17.33", "1.37", "73.0")]),
    ]

    hint_cols = [
        ("ImprovePriority", "text"),
        ("N (sym / trades)", "text"),
        ("Lever tested today", "text"),
        ("Outcome", "text"),
    ]
    hints = [
        tr(["mtm_giveback_stop / winner_peak_giveback", "202/253 + 31/34", "Trail-1 break-even +14% / +20%", "DISMISS"]),
        tr(["slow_target_grind", "156/190", "Target 1.18/1.15; time-stop 40/80; partial + ladder", "1.18 weaker consider; 40d CONSIDER; 1.15 / partial / ladder DISMISS"]),
        tr(["fat_stops", "139/205", "Stop tighten 0.940 / 0.945; time-stop", "Stop tighten DISMISS; 40d CONSIDER"]),
        tr(["post_target_quick_stop", "88/125", "Reentry bars 10/15 mode=none", "DISMISS (modes stop_loss / min_stack not run)"]),
        tr(["shallow_entry_sma50_fail / band_tighten", "56/71 + 190/303", "Dip 1.041 / 1.030", "1.041 HOLD (N −27%); freeze 1.055"]),
        tr(["false_start_2022_2023", "50/59", "Slope 0.05 / 0.0643", "PO DISMISS"]),
        tr(["small_target_wins / target expand tension", "41/47 + 63/579", "Target 1.25 / 1.30", "DISMISS (WR / host DD collapse)"]),
        tr(["stop_pct_tension expand", "51/544", "Stop 0.92 / 0.90", "PO DISMISS (Ann ROR from slower book)"]),
    ]

    freeze_cols = [("Knob", "text"), ("Freeze (DailyRun / research control)", "text"), ("Notes", "text")]
    freeze_rows = [
        tr(["Universe", "tradable 2010 / ADV$2m <strong>764</strong>", "<code>VZ_tradable_2010_adv2m_universe.csv</code>. Isolated <code>-s</code> DuckDB. Do not overwrite <code>RL_universe.csv</code>."]),
        tr(["<code>rl_dip_pct</code>", "1.055", "1.041 HOLD only (N −27%). 1.030 DISMISS."]),
        tr(["<code>rl_expansion</code>", "1.163", "Not A/B’d this restart."]),
        tr(["<code>rl_stop_pct</code>", "0.934", "Expand 0.92/0.90 and tighten 0.940/0.945 all DISMISS."]),
        tr(["<code>rl_target_pct</code>", "1.20 (SMA 50)", "1.25/1.30 DISMISS. 1.15 no. 1.18 weaker CONSIDER."]),
        tr(["<code>rl_slope_threshold</code>", "0 (off)", "0.05 / 0.0643 PO DISMISS."]),
        tr(["Trails / BE", "off", "14% / 20% DISMISS."]),
        tr(["<code>rl_post_target_reentry_bars</code>", "0", "10 / 15 mode=none DISMISS."]),
        tr(["Partial / ladder", "off", "Both DISMISS."]),
        tr(["<code>rl_exit_days</code>", "10000 (off)", "<strong>PO CONSIDER 40</strong> after +29% (<code>rl_exit_percent=0.29</code>). Not adopted."]),
        tr(["Cash / host seed", "$47,500 / $500,000", "Sheet dollars omitted from HTML compares (Paul request)."]),
    ]

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL 764 restart — PO report 2026-08-28</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --hi:#1e3a2f; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}}
header,main{{max-width:1400px;margin:0 auto;padding:0 1.1rem}}
header{{padding-top:1.4rem}}
h1{{font-size:1.45rem;margin:0 0 .4rem}}
h2{{font-size:1.12rem;margin:1.4rem 0 .45rem;color:var(--accent)}}
h3{{font-size:1rem;margin:1rem 0 .35rem}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout,.section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.85rem 1rem;margin:.85rem 0}}
ul,ol{{margin:.4rem 0 .2rem 1.2rem}}
li{{margin:.28rem 0}}
a{{color:#7eb8e8}}
code{{font-size:.88em}}
.toc a{{margin-right:.75rem}}
.table-wrap{{overflow-x:auto;margin:.5rem 0}}
table.sortable{{border-collapse:collapse;width:100%;font-size:.76rem;min-width:880px}}
th,td{{border-bottom:1px solid var(--line);padding:.32rem .4rem;text-align:left;vertical-align:top}}
table.num-table td:nth-child(n+3){{text-align:right}}
tr.hi-row{{background:var(--hi)}}
tr.ctrl-row{{background:var(--ctrl)}}
th.sortable-th{{cursor:pointer;user-select:none;white-space:nowrap}}
th.sortable-th:hover{{background:#2a3545}}
.sort-ind{{display:inline-block;width:0.9em;margin-left:4px;color:#94a3b8;font-size:10px}}
th.sort-asc .sort-ind::after{{content:"▲";color:#e7ecf3}}
th.sort-desc .sort-ind::after{{content:"▼";color:#e7ecf3}}
</style>
</head>
<body>
<header>
<h1>Rocket Launcher (RL) — tradable 764 restart</h1>
<p class="muted">Product owner (PO) pack for everything after the from-scratch 764 restart.
Date <strong>2026-08-28</strong>. In-sample (IS) = entry &lt; 2024-01-01.
Out-of-sample (OOS) = entry ≥ 2024-01-01 (report-only; never used to retune).
Click column headers to sort. Highlighted rows = live consider or control.
Research ≠ gold ≠ DailyRun. Sheet / total PnL $ omitted from tables (Paul request).</p>
<p class="muted toc">
<a href="#decide">Decide</a>
<a href="#judge">How judged</a>
<a href="#freeze">Freeze</a>
<a href="#univ">Universe</a>
<a href="#log">Decision log</a>
<a href="#control">Control book</a>
<a href="#consider">Consider pile</a>
<a href="#all">All arms</a>
<a href="#fill">Fill bug</a>
<a href="#wf">Walk-forward</a>
<a href="#hints">ImprovePriority</a>
<a href="#next">Next</a>
</p>
</header>
<main>

<div class="callout" id="decide">
<h2 style="margin-top:0">What to decide</h2>
<p>We restarted RL on a <strong>from-scratch 764-name tape</strong> (listed by 2010, Close ≥ $5, 20-session average daily dollar volume (ADV$) ≥ $2m as-of 2023-12-29). Production <code>RL_universe.csv</code> (59 names) was <strong>not</strong> overwritten.</p>
<ul>
<li><strong>Freeze is still DailyRun:</strong> dip 1.055, expansion 1.163, stop 0.934, Simple Moving Average (SMA) 50 target 1.20, slope off, trails off, time-stop off (<code>rl_exit_days=10000</code>), cash $47,500.</li>
<li><strong>Open PO item:</strong> <code>rl_exit_days=40</code> after a +29% mark-to-market print — <strong>CONSIDER</strong>, not adopted. Walk-forward: 40d beat off on annualized rate of return (Ann ROR) in <strong>9 of 14</strong> test years. Lost 2014 / 2018 / 2022 / 2023. Crushed 2020.</li>
<li><strong>Weaker shelf:</strong> target 1.18 — IS recycle (Ann ROR / hold days / host drawdown (DD)) but OOS Ann ROR 31.7→25.8 and overlay DD 17.1→20.5. Do not stack on 40d until 40d is frozen.</li>
<li><strong>Do not DailyRun-wire</strong> from these stamps. Gold needs an explicit freeze + parity/reconcile after you pick 40d or leave it off.</li>
</ul>
</div>

<div class="section" id="judge">
<h2>How we judged</h2>
<ul>
<li><strong>One knob per stamp.</strong> Same 764 universe, same exit identity when testing entries (and vice versa). OOS is report-only. No OOS retune.</li>
<li><strong>House auto-rule</strong> (quality-first): DISMISS if IS average PnL% drops ≥0.10 vs control, or overlay Max DD +3pp. That is why 40d printed house DISMISS (Avg 4.42→3.54) even though Ann ROR and host DD improved.</li>
<li><strong>PO scoreboard on turnover knobs:</strong> a lower Avg can still be CONSIDER if Ann ROR is up and drawdown is down. Used for 40d CONSIDER and for not adopting 1.15. OOS remains a veto, not a retune trigger.</li>
<li><strong>Overlay Max DD</strong> (Closed dollars on $500k, no position cap) can lie and can exceed 100%. Prefer <strong>host EquityMeta passive DD</strong> when both exist. Overlay Calmar in the tables uses overlay Ann ROR / overlay DD.</li>
<li><strong>Picked 40 after seeing 80</strong> on the same tape — labeled in-sample selection. Walk-forward was the next rigor step (locked 40 vs off; no 30/50; no 40×1.18).</li>
</ul>
</div>

<div class="section" id="freeze">
<h2>Research freeze (still DailyRun unless you adopt 40d)</h2>
<p class="muted">Control Closed: <code>rl_tradable_2010_adv2m_20260828/runs/tradable/RL_Closed_260828112205.csv</code> (2,356 trades). Isolated <code>-s</code> DuckDB.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{ths(freeze_cols)}</tr></thead>
<tbody>{"".join(freeze_rows)}</tbody></table></div>
</div>

<div class="section" id="univ">
<h2>1. Starting over — universe, not a Paul cut</h2>
<p>Stamp <a href="rl_tradable_2010_adv2m_20260828/compare.html"><code>rl_tradable_2010_adv2m_20260828</code></a>. Traits only — not an RL winner list. 25 of 59 house names fail the 2010/ADV$ screen and stay on the whitelist only:
<code>ABUS, APP, CMCL, CRWD, DOCN, EDVMF, FIVN, FN, GHM, HUBS, KINS, LMB, LMND, NGVC, NTRA, NVAX, NXT, PDEX, PSIX, RNG, SPRY, TGB, TGLS, TORXF, TPC</code>.</p>
<p>House 59 and List2 look better on IS (and house 59 on OOS) because they are <strong>selected names</strong>. Tradable 764 is the honest book. List2 OOS Avg 2.96% is a failed IS winner-cut. <strong>Do not KEEP 59 because it is prettier. Do not Paul-cut 764.</strong></p>
<p class="muted">Same-day related: Paul8/Paul78 vs List2 (<a href="rl_univ_compare_paul8_paul78_20260828/compare.html">stamp</a>) — Paul8 OOS Avg 3.99% vs List2 2.96% is still a winner-cut. HOLD only, not gold, not the 764 param hunt.</p>
<div class="table-wrap"><table class="sortable num-table"><thead><tr>{ths(m_cols)}</tr></thead>
<tbody>{"".join(univ_rows)}</tbody></table></div>
</div>

<div class="section" id="log">
<h2>2. Master decision log (every test after the 764 restart)</h2>
<p class="muted">ImprovePriority source: <code>RL_ImproveHints_260828112205</code> on the tradable Closed. Click headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{ths(dec_cols)}</tr></thead>
<tbody>{"".join(decisions)}</tbody></table></div>
</div>

<div class="section" id="control">
<h2>3. Control book (764 freeze)</h2>
<p class="muted">Host Sharpe 0.32, host Max DD 17.72%, aggressive Max DD 45.04%, 694 max days underwater. Mean Paul 3.60 / FIT 0.37 / robust FIT −2.35 on the FULL book. Overlay Max DD 37.74% is the uncapped Closed replay — worse than the host account.</p>
<div class="table-wrap"><table class="sortable num-table"><thead><tr>{ths(m_cols)}</tr></thead>
<tbody>{"".join(control_rows)}</tbody></table></div>
</div>

<div class="section" id="consider">
<h2>4. Consider pile vs control</h2>
<p><strong>40d time-stop</strong> is the live consider. Fill is close-day <em>open vs original entry</em> (not the +29% print). First Closed <code>260828161053</code> is <strong>VOID</strong> (Python labeled <code>RL_EXIT_DAYS</code> but sold the stop). Corrected stamp <code>260828184602</code>: 170 timed exits, mean about +26% from entry. Host DD 17.7→7.8. OOS Avg essentially flat (3.77→3.74); OOS Ann ROR 31.7→34.1.</p>
<p><strong>1.18 target</strong> is the weaker consider (IS Ann ROR 16.4→19.1, host DD 17.7→15.1; OOS Ann ROR 31.7→25.8, overlay DD 17.1→20.5). <strong>1.15 is no</strong> (PF 1.69→1.57, avg win 29→15). Do not mix 40d × 1.18 on one stamp.</p>
<div class="table-wrap"><table class="sortable num-table"><thead><tr>{ths(m_cols)}</tr></thead>
<tbody>{"".join(consider_rows)}</tbody></table></div>
<h3>FULL-book host / FIT (not a DailyRun score)</h3>
<div class="table-wrap"><table class="sortable num-table"><thead><tr>{ths(fit_cols)}</tr></thead>
<tbody>{"".join(fit_rows)}</tbody></table></div>
</div>

<div class="section" id="all">
<h2>5. Every arm we ran (IS / OOS)</h2>
<p class="muted">Canonical book fields that exist on these stamps. Host Max DD is the full-run EquityMeta (not an IS/OOS split). “—” = not in that stamp’s SUMMARY. BE-trail rows are FULL-book overlay only (that generator did not print IS/OOS in SUMMARY).</p>
<div class="table-wrap"><table class="sortable num-table"><thead><tr>{ths(m_cols)}</tr></thead>
<tbody>{"".join(all_arm_rows)}</tbody></table></div>
</div>

<div class="section" id="fill">
<h2>6. Time-stop fill bug (first 40/80 print VOID)</h2>
<p>PnL% was always vs <strong>original entry</strong>, not rebased to the +29% print. The bad Avgs (~0.5% / 0.9%) were not a cost-basis issue. After the countdown, Python set fill to the day’s open, then a later block treated <code>RL_EXIT_DAYS</code> with <code>hit_timed == 0</code> only and <strong>fell through to the stop fill</strong>. AWK keeps the open.</p>
<p>Example (ticker A): entry 88.88, close-day open 118.69, VOID report sold ~78.19 (stop) → about −12%. After the fix: fill 118.69 → about +33.5%. All 170 <code>RL_EXIT_DAYS</code> rows on the corrected 40d Closed fill at open. The fix is in <code>stock_analysis/rocket_rl.py</code> (keep race fill at open; do not overwrite with stop). Use Closed <code>260828184602</code>, not <code>260828161053</code>.</p>
</div>

<div class="section" id="wf">
<h2>7. Walk-forward — locked 40d vs off</h2>
<p class="muted"><a href="rl_time_stop_40_wf_tradable_20260828/compare.html"><code>rl_time_stop_40_wf_tradable_20260828</code></a>. Train 3 years → test 1 year, step 1 year, entry-date slices of existing Closeds. No engine re-run. No 30/50. No 1.18. Overlay DD on 1y slices is noisy — prefer fold Ann ROR + Avg + the full-book host DD (17.7→7.8).</p>
<ul>
<li>14 test folds, both arms N≥15: Ann ROR win <strong>9/14</strong>; overlay DD win 7/14 (ties counted as not a DD win in the stamp); Avg win 7/14.</li>
<li>40d <strong>lost Ann ROR</strong> in 2014, 2018, 2022, 2023. Crushed 2020 (18.2→56.1). That is why this stays CONSIDER, not gold.</li>
<li>Train-window “would we have picked 40?” is report-only (first five trains would have stayed off). Embargoed sleeve still beats always-off on Ann ROR (23.7 vs 18.3) with Avg 4.35 vs 4.13.</li>
</ul>
<div class="table-wrap"><table class="sortable num-table"><thead><tr>{ths(wf_cols)}</tr></thead>
<tbody>{wf_body}</tbody></table></div>
<h3>Pooled non-overlapping test years</h3>
<div class="table-wrap"><table class="sortable num-table"><thead><tr>{ths(wf_pool_cols)}</tr></thead>
<tbody>{"".join(wf_pool)}</tbody></table></div>
</div>

<div class="section" id="hints">
<h2>8. ImprovePriority coverage</h2>
<div class="table-wrap"><table class="sortable"><thead><tr>{ths(hint_cols)}</tr></thead>
<tbody>{"".join(hints)}</tbody></table></div>
<p class="muted">Not run (and not next unless you ask): post-target reentry <em>mode</em> (stop_loss / min_stack); trail after +15% with a real trail stop (break-even already died); cut_the_losers / Standard &amp; Poor's 500 (SPY) intermediate-trend weak block. Do not re-search dismissed knobs. Do not pile slope onto dip 1.041.</p>
</div>

<div class="section">
<h2>9. Dismissed in one line (do not re-grid)</h2>
<ul>
<li>Break-even trail 14/20% — quality down (WR/Avg/OOS).</li>
<li>Post-target bars 10/15 — IS Avg down.</li>
<li>Stop expand 0.92/0.90 — PO: Ann ROR from a slower book (0.90 IS 16.4→15.0, 104→141d). 0.92 overlay DD +5pp.</li>
<li>Stop tighten 0.940/0.945 — Avg/WR down.</li>
<li>Target expand 1.25/1.30 — WR/host DD collapse; OOS Ann ROR down.</li>
<li>Target 1.15 — too much winner-clip; OOS Ann ROR down.</li>
<li>Partial 50%/+20% — IS recycle, OOS Ann ROR 31.7→27.8.</li>
<li>Scale ladder — Avg 4.42→2.5, avg win ~29→12.</li>
<li>Dip 1.030 — IS quality down (do not KEEP from OOS LEAN KEEP).</li>
<li>Slope 0.05/0.0643 — PO DISMISS (tiny IS Avg; host DD 17.7→18.3; 0.0643 overlay DD 37.7→42.2).</li>
<li>80d time-stop — not the consider pick vs 40 (in-sample selection labeled).</li>
</ul>
</div>

<div class="section" id="next">
<h2>10. Recommended next steps (after 40d yes/no)</h2>
<ol>
<li><strong>Decide 40d.</strong> Adopt → new freeze <code>rl_exit_days=40</code>, re-score IS/OOS under that freeze, still research-only until parity. Leave off → CONSIDER stays on the shelf; DailyRun unchanged.</li>
<li><strong>Do not mix 1.18 on the same stamp.</strong> If 40 is frozen and you still want 1.18, that is a new one-knob A/B.</li>
<li><strong>Universe is not the next param.</strong> 764 is the research tape. A smaller live sleeve would be a named rule (ADV / relative strength / sector cap) with its own walk-forward — not another winner list.</li>
<li><strong>DailyRun last:</strong> explicit wire + engine/sheet reconcile. These stamps do not do that.</li>
</ol>
</div>

<p class="muted">Artifacts live under <code>drive/paul_experiments/rl_*_20260828/</code>.
Generator: <code>tools/rl_764_restart_po_report.py</code>.</p>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT}", flush=True)
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        subprocess.run(
            [
                sys.executable,
                str(ntfy),
                "--path",
                str(OUT),
                "-t",
                "RL 764 PO master report",
                "-m",
                "PO pack: 764 restart, all one-knob A/Bs, 40d CONSIDER + walk-forward. Freeze still DailyRun.",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
