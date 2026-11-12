from pathlib import Path
p = Path("_tmp_amzn_sc_20221208_diag.py")
t = p.read_text(encoding="utf-8")

old_dec = '''    # Detailed Dec 2022 classification
    T.write("\\nDetailed Dec 2022 classification (HALF_UP compares):")
    for d in [f"2022-12-{dd:02d}" for dd in range(1, 16)]:
        try:
            i = bi(idx, d)
        except Exception:
            continue
'''

new_dec = '''    # Detailed Nov 2022 first-retest window + Dec 2022
    T.write("\\nDetailed bars around first retest 2022-11-04 (and +2 signal window):")
    for d in ["2022-11-02", "2022-11-03", "2022-11-04", "2022-11-07", "2022-11-08", "2022-11-09", "2022-11-10"]:
        if pd.Timestamp(d) not in idx:
            T.write(f"  {d}: not a trading day")
            continue
        i = bi(idx, d)
        lo_r = _half_up(lo[i])
        cl_r = _half_up(cl[i])
        op_r = _half_up(op[i])
        is_ab = cl_r < ZL
        is_rt = lo_r <= ZH and cl_r > ZH
        is_gr = cl_r > op_r and cl_r > ZH
        T.write(
            f"  {d} O={op[i]:.4f}->{op_r:.2f} L={lo[i]:.4f}->{lo_r:.2f} C={cl[i]:.4f}->{cl_r:.2f} "
            f"abandon={is_ab} retest={is_rt} green={is_gr}"
        )

    T.write("\\nDetailed Dec 2022 classification (HALF_UP compares; skip non-sessions):")
    for d in [f"2022-12-{dd:02d}" for dd in range(1, 16)]:
        if pd.Timestamp(d) not in idx:
            continue
        i = bi(idx, d)
'''

if old_dec not in t:
    raise SystemExit("dec block not found")
t = t.replace(old_dec, new_dec, 1)

old_sum = '''    if first_abandon and (first_retest is None or first_abandon < (first_retest or "9999")):
        T.write(
            "LIKELY ROOT: abandon-kill under stop_looking — Close < zl occurred "
            f"on {first_abandon} BEFORE any valid retest, so SC resume emits None "
            "(sheet Results 2022-12-08 has no parent rocket in zones paste)."
        )
    elif bd(idx, fill) == TARGET_FILL:
        T.write("Engine WOULD fill 2022-12-08 from find_wpbr — investigate occupancy/SC wiring.")
    elif bd(idx, fill) is None:
        T.write(
            "find_wpbr returns no fill by 2022-12-08. Sheet Results 12/8/2022 is orphaned "
            "vs zones paste (zones only show first rocket 3/25/2019)."
        )
'''

new_sum = '''    T.write(
        "MECHANICS: stop_looking takes the FIRST retest after scan_start; then needs a green "
        "Close>Open & Close>zh within max_days_after_retest=2 (inclusive of retest bar)."
    )
    if first_abandon and (first_retest is None or first_abandon < (first_retest or "9999")):
        T.write(
            "LIKELY ROOT: abandon-kill under stop_looking — Close < zl occurred "
            f"on {first_abandon} BEFORE any valid retest, so SC resume emits None."
        )
    elif first_retest and bd(idx, rt) == first_retest and bd(idx, fill) is None:
        T.write(
            f"LIKELY ROOT: SC resume finds first retest on {first_retest} but NO green signal "
            "within +2 bars -> (retest, None, None). Later Dec 6-8 retest/green bars are "
            "IGNORED because the scan already committed to the earlier failed retest window. "
            "Sheet Results 12/8/2022 has no Second Rocket in zones.tsv (only first rocket 3/25/2019)."
        )
    elif bd(idx, fill) == TARGET_FILL:
        T.write("Engine WOULD fill 2022-12-08 from find_wpbr — investigate occupancy/SC wiring.")
    elif bd(idx, fill) is None:
        T.write(
            "find_wpbr returns no fill by 2022-12-08. Sheet Results 12/8/2022 is orphaned "
            "vs zones paste (zones only show first rocket 3/25/2019)."
        )
'''

if old_sum not in t:
    raise SystemExit("sum block not found")
t = t.replace(old_sum, new_sum, 1)
p.write_text(t, encoding="utf-8")
print("ok")
