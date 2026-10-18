"""One-shot: merge 22/20/8 no-overhead slice into neighborhood artifacts. Do not wipe extras."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "drive" / "paul_experiments" / "wpbr_15_10_4_neighborhood_20261002"
CTRL_CLOSED = (
    "C:/Users/songg/Downloads/stockresearch/"
    "tmp_wpbr_overhead20_vs22_t20s8_ab_20261002/control/WPBR_Closed_261002051403.csv"
)

NOH_ROW = (
    "<tr><td>22/20/8 no overhead (clear sky)</td><td>extra slice</td><td>22</td><td>20</td><td>8</td>"
    "<td>extra slice (not in original 125) — live 22/20/8, no constraining older zone</td>"
    "<td>2996</td><td>53.4%</td><td>5.92%</td><td>2.21</td><td>12.39%</td>"
    "<td>18.14%</td><td>16.60%</td><td>30.75%</td><td>5.88%</td><td>2.20</td><td>12.39%</td>"
    "<td>-1.42%</td><td>$4,255.32</td><td>extra / control slice</td></tr>"
)
CTRL_MARKER = (
    "<tr><td>22/20/8 live</td><td>live</td><td>22</td><td>20</td><td>8</td><td></td><td>4249</td>"
    "<td>52.4%</td><td>5.29%</td><td>1.98</td><td>12.39%</td><td>19.88%</td><td>18.02%</td>"
    "<td>34.71%</td><td>5.25%</td><td>1.98</td><td>12.39%</td><td>—</td><td>$4,255.32</td>"
    "<td>control</td></tr>"
)


def th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{label}<span class="sort-ind"></span></th>'
    )


def patch_html() -> None:
    path = STAMP / "compare.html"
    html = path.read_text(encoding="utf-8")
    if "22/20/8 no overhead (clear sky)" in html:
        print("html already has no-overhead row")
        return
    start = html.find("<h2>Every cell</h2>")
    if start < 0:
        raise SystemExit("Every cell heading missing")
    key = "<tr><td>22/20/8 live</td><td>live</td>"
    pos = html.find(key, start)
    if pos < 0:
        raise SystemExit("control live row not found")
    end = html.find("</tr>", pos)
    if end < 0:
        raise SystemExit("control live row close not found")
    html = html[: end + 5] + NOH_ROW + html[end + 5 :]
    old_q = "also add them to this summary wpbr_15_10_4_neighborhood_20261002</blockquote>"
    new_q = (
        "also add them to this summary wpbr_15_10_4_neighborhood_20261002. "
        "can you make sure the 22/20/8 with no overhead is written here as well</blockquote>"
    )
    if old_q not in html:
        raise SystemExit("blockquote tail not found")
    html = html.replace(old_q, new_q, 1)
    old_p = "<p>Paul also asked to park seven extra packages on this same summary:"
    new_p = (
        "<p>He also asked to write the live 22/20/8 freeze here as the "
        "<strong>no-overhead (clear sky)</strong> slice only — trades with no constraining "
        "older zone. That is not the G≥22% subset, and it is not part of the 125-cell grid.</p>\n"
        + old_p
    )
    if old_p not in html:
        raise SystemExit("layman extra-packages paragraph not found")
    html = html.replace(old_p, new_p, 1)
    old_every = "Original 125 plus extra packages. Full book"
    new_every = "Original 125 plus extra packages plus the live 22/20/8 no-overhead slice. Full book"
    if old_every not in html:
        raise SystemExit("every-cell note not found")
    html = html.replace(old_every, new_every, 1)

    metric_rows = [
        ("Trades", ["2996", "2462", "534", "4249", "−1253", "3450", "799"]),
        ("Win rate", ["53.4%", "53.2%", "54.3%", "52.4%", "+1.0%", "52.1%", "53.6%"]),
        ("Avg %", ["5.92%", "5.88%", "6.12%", "5.29%", "+0.63%", "5.25%", "5.47%"]),
        ("Median %", ["20.00%", "20.00%", "20.00%", "20.00%", "+0.00%", "20.00%", "20.00%"]),
        ("Profit factor", ["2.21", "2.20", "2.24", "1.98", "+0.22", "1.98", "1.98"]),
        ("Max DD %", ["12.39%", "12.39%", "3.74%", "12.39%", "+0.00%", "12.39%", "3.74%"]),
        (
            "Annualized rate of return (Ann ROR) %",
            ["18.14%", "16.60%", "30.75%", "19.88%", "−1.75%", "18.02%", "34.71%"],
        ),
        ("Avg days held", ["126.0", "135.9", "80.8", "103.8", "+22.2", "112.8", "65.2"]),
        ("Median days held", ["87.0", "97.0", "53.0", "64.0", "+23.0", "71.0", "36.5"]),
        ("Avg winner %", ["20.27%", "20.25%", "20.38%", "20.38%", "−0.11%", "20.33%", "20.58%"]),
        ("Avg loser %", ["−10.53%", "−10.46%", "−10.84%", "−11.31%", "+0.79%", "−11.17%", "−11.97%"]),
        ("Expectancy %", ["5.92%", "5.88%", "6.12%", "5.29%", "+0.63%", "5.25%", "5.47%"]),
        (
            "Avg % without max winner",
            ["5.90%", "5.85%", "6.07%", "5.28%", "+0.62%", "5.23%", "5.38%"],
        ),
        ("Calmar", ["1.46", "1.34", "8.22", "1.61", "−0.14", "1.45", "9.28"]),
        ("Sharpe", ["0.63", "0.61", "1.12", "0.63", "+0.00", "0.61", "1.12"]),
        ("Trades / year", ["181.14", "170.99", "195.04", "256.90", "−75.76", "239.61", "291.83"]),
    ]
    mhead = "".join(
        [
            th("Metric", "text"),
            th("No overhead FULL", "num"),
            th("No overhead IS", "num"),
            th("No overhead OOS", "num"),
            th("Live full book FULL", "num"),
            th("Δ vs live FULL", "num"),
            th("Live full book IS", "num"),
            th("Live full book OOS", "num"),
        ]
    )
    body = []
    for lab, vals in metric_rows:
        body.append("<tr><td>" + lab + "</td>" + "".join(f"<td>{v}</td>" for v in vals) + "</tr>")
    section = f"""
<h2>Extra slice: live 22/20/8, no overhead (clear sky)</h2>
<p class="note">Paul asked to write the live 22/20/8 freeze here as well, but only the
<strong>no-overhead / clear sky</strong> bin: buys with no constraining older zone above.
This is <strong>not</strong> the G≥22% overhead-present subset. It is not one of the original
125 cells (13–17 / 8–12 / 2–6). Numbers reuse stamp 261002051403 Closed, with the same
overhead-gap recovery as the fraction-grid page (join to 80/40 OVERHEAD_GAP_PCT, then zone
and checkpoint fallback). Slot cash is the live engine slot, about $4,255.32. Max DD and
Sharpe still come from the host equity curve, same as the frac-grid bin table. Symbol Paul
Score / FIT aggregates are the host book, not a separate Summary for this slice. Research
only. Not gold. Not DailyRun.</p>
<p class="note">Clear-sky full book: N 2996, win rate 53.4%, average 5.92%,
annualized rate of return 18.14%, average days held 126.0.
In-sample Ann ROR 16.60% (N 2462). Out-of-sample Ann ROR 30.75%
(N 534, report-only). Full live 22/20/8 book remains on this page: N 4249,
Ann ROR 19.88%.</p>
<p class="swipe-note">Swipe sideways to see more columns.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{mhead}</tr></thead><tbody>{''.join(body)}</tbody></table></div>

"""
    needle = "<h2>Extra packages (target 7"
    if needle not in html:
        raise SystemExit("extra packages heading missing; will not wipe extras")
    html = html.replace(needle, section + needle, 1)
    if "16/7/3" not in html or "17/7/5" not in html:
        raise SystemExit("extras rows missing after patch")
    path.write_text(html, encoding="utf-8")
    print("patched", path)


def patch_csv() -> None:
    path = STAMP / "summary.csv"
    text = path.read_text(encoding="utf-8")
    if "control_no_overhead" in text:
        print("csv already has no-overhead")
        return
    rows = [
        (
            "control_no_overhead,22/20/8 no overhead (clear sky),"
            "extra (clear-sky slice of live control),,22,20,8,1.20,0.92,4255.319149,952,"
            "FULL,2996,53.4045,5.9248,20.0000,2.2087,12.3878,18.1378,126.0435,87.0000,"
            "1.4642,0.6275,20.2731,-10.5277,5.9248,5.9012,181.1437,extra / control slice,"
            f"{CTRL_CLOSED}"
        ),
        (
            "control_no_overhead,22/20/8 no overhead (clear sky),"
            "extra (clear-sky slice of live control),,22,20,8,1.20,0.92,4255.319149,952,"
            "IS,2462,53.2088,5.8831,20.0000,2.2028,12.3878,16.6013,135.8502,97.0000,"
            "1.3401,0.6096,20.2487,-10.4619,5.8831,5.8543,170.9917,extra / control slice,"
            f"{CTRL_CLOSED}"
        ),
        (
            "control_no_overhead,22/20/8 no overhead (clear sky),"
            "extra (clear-sky slice of live control),,22,20,8,1.20,0.92,4255.319149,952,"
            "OOS,534,54.3071,6.1171,20.0000,2.2352,3.7386,30.7460,80.8368,53.0000,"
            "8.2239,1.1192,20.3830,-10.8382,6.1171,6.0721,195.0435,extra / control slice,"
            f"{CTRL_CLOSED}"
        ),
    ]
    needle = (
        "control,22/20/8 live,control,,22,20,8,1.20,0.92,4255.319149,1050,OOS,799,"
    )
    idx = text.find(needle)
    if idx < 0:
        raise SystemExit("control OOS csv row not found")
    end = text.find("\n", idx)
    if end < 0:
        raise SystemExit("control OOS csv newline not found")
    insert = "\n".join(rows) + "\n"
    text = text[: end + 1] + insert + text[end + 1 :]
    if "oh16_tg07_st03" not in text:
        raise SystemExit("csv extras missing after patch")
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def patch_baseline() -> None:
    path = STAMP / "BASELINE.md"
    text = path.read_text(encoding="utf-8")
    if "no-overhead (clear sky)" in text or "no overhead (clear sky)" in text:
        print("baseline already has no-overhead")
        return
    old_q = (
        "also add them to this summary wpbr_15_10_4_neighborhood_20261002\n"
    )
    new_q = (
        "also add them to this summary wpbr_15_10_4_neighborhood_20261002. "
        "can you make sure the 22/20/8 with no overhead is written here as well\n"
    )
    if old_q not in text:
        raise SystemExit("baseline quote tail not found")
    text = text.replace(old_q, new_q, 1)
    old = (
        "Seven extra packages with a 7% target sit on the same page: 16/7/3, 16/7/4, 16/7/5, "
        "17/7/2, 17/7/3, 17/7/4, and 17/7/5. They are not part of the original 125. "
        "Target 7 is outside the frozen neighborhood (target 8-12). DailyRun stays 22/20/8.\n"
    )
    new = old + (
        "\nPaul also asked for the live 22/20/8 freeze as the no-overhead (clear sky) slice only: "
        "trades with no constraining older zone. That is not the G>=22% subset and not part of "
        "the original 125. Same Closed stamp 261002051403 and the same G recovery as the "
        "fraction-grid page (80/40 OVERHEAD_GAP_PCT join). Research only.\n"
    )
    if old not in text:
        raise SystemExit("baseline extras paragraph not found")
    text = text.replace(old, new, 1)
    freeze = "- Control full N 4249, Ann ROR 19.88%, in-sample 18.02%, slot $4,255.32.\n"
    freeze_new = freeze + (
        "- Extra slice, live 22/20/8 no overhead (clear sky), not in the 125, not G>=22%: "
        "FULL N 2996, WR 53.4%, avg 5.92%, Ann ROR 18.14%, days 126.0; "
        "IS N 2462 Ann ROR 16.60%; OOS N 534 Ann ROR 30.75% (report-only). "
        "Same slot cash. Source Closed 261002051403 + frac-grid G recovery.\n"
    )
    if freeze not in text:
        raise SystemExit("baseline control full line not found")
    text = text.replace(freeze, freeze_new, 1)
    if "16/7/3" not in text:
        raise SystemExit("baseline extras missing after patch")
    path.write_text(text, encoding="utf-8")
    print("patched", path)


if __name__ == "__main__":
    patch_html()
    patch_csv()
    patch_baseline()
    print("done")
