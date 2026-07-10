#!/usr/bin/awk -f

BEGIN { 
    FS = ","; OFS = "\t" 
    rsi_period = 14; atr_period = 14
}

function to_iso(d) {
    gsub(/[ \t"]/, "", d); split(d, a, /[\/\-]/)
    if (length(a[3]) == 4) return sprintf("%04d%02d%02d", a[3], a[1], a[2])
    if (length(a[1]) == 4) return sprintf("%04d%02d%02d", a[1], a[2], a[3])
    return ""
}

function abs(v) { return v < 0 ? -v : v }

# PHASE 1: Process the History File (First file in ARGV)
FILENAME == ARGV[1] {
    if (FNR == 1) next
    symbol = toupper($3)
    id = $14; d_iso = to_iso($1); qty = $5 + 0; px = $6 + 0
    
    if (id == "") next

    if (!start_iso[id] || d_iso < start_iso[id]) { start_iso[id] = d_iso }
    if (d_iso > end_iso[id]) { end_iso[id] = d_iso; final_exit_px[id] = px }
    
    # Store symbols we actually have trades for
    active_symbols[symbol] = 1
    trade_to_symbol[id] = symbol

    if ($4 == "Buy") { 
        daily_inv_change[id, d_iso] += qty
        realized_pnl[id] -= (qty * px)
    } else { 
        daily_inv_change[id, d_iso] -= qty
        realized_pnl[id] += (qty * px)
    }
    next
}

# PHASE 2: Process Price Files
# Skip the history file if it's caught in the *.csv glob
FILENAME == ARGV[1] { next }

# Reset indicators for every new price file
FNR == 1 {
    # Extract Symbol from Filename (e.g., AEM.csv -> AEM)
    current_file = FILENAME
    sub(/.*\//, "", current_file); sub(/.*\\/, "", current_file); sub(/\.csv$/, "", current_file)
    file_symbol = toupper(current_file)
    
    # Reset technical indicators
    avg_g = 0; avg_l = 0; atr = 0; prev_cl = 0
    vol_sum = 0; delete prices
    next
}

{
    # Check if we even have trades for this symbol
    if (!active_symbols[file_symbol]) next
    if ($3 == "" || $3 ~ /[a-zA-Z]/) next

    c_iso = to_iso($3); hi=$5+0; lo=$6+0; cl=$7+0; vol=$8+0

    # Indicators
    if (prev_cl > 0) {
        # RSI
        diff = cl - prev_cl; g = (diff>0?diff:0); l = (diff<0?-diff:0)
        avg_g = ((avg_g * 13) + g) / 14; avg_l = ((avg_l * 13) + l) / 14
        rsi = (avg_l > 0) ? 100 - (100 / (1 + (avg_g/avg_l))) : 100
        # ATR
        tr = hi-lo; t1=abs(hi-prev_cl); t2=abs(lo-prev_cl)
        tr = (t1>tr?t1:tr); tr = (t2>tr?t2:tr)
        atr = ((atr * 13) + tr) / 14
    }
    prices[FNR] = cl; s=0; c=0; for(i=FNR; i>FNR-8 && i>0; i--){s+=prices[i]; c++}
    sma8 = s/c
    vol_sum += vol; vol_avg = vol_sum / FNR

    # Check all trades associated with this symbol
    for (id in start_iso) {
        if (trade_to_symbol[id] != file_symbol) continue
        
        if (c_iso >= start_iso[id] && c_iso <= end_iso[id]) {
            curr_inv[id] += daily_inv_change[id, c_iso]
            if (curr_inv[id] <= 0) continue 

            if (hi > mfe[id]) { mfe[id] = hi; mfe_dt[id] = $3 }
            if (lo < mae[id] || mae[id] == 0) { mae[id] = lo; mae_dt[id] = $3 }
            
            impact_unit = (cl - final_exit_px[id])
            
            # --- SIGNALS ---
            if (vol > (vol_avg * 1.5) && cl > prev_cl)
                report[id] = report[id] sprintf("\n  [BUY: Vol Accum] %s at $%.2f", $3, cl)

            if (vol > (vol_avg * 1.5) && cl < prev_cl) {
                imp = curr_inv[id] * impact_unit
                report[id] = report[id] sprintf("\n  [SELL: Vol Dist] %s at $%.2f | Impact: %s$%.2f", $3, cl, (imp>=0?"+":"-"), abs(imp))
            }
            if (cl > (sma8 + (2 * atr))) {
                imp = curr_inv[id] * impact_unit
                report[id] = report[id] sprintf("\n  [TRIM: Parabolic] %s at $%.2f | Impact: %s$%.2f", $3, cl, (imp>=0?"+":"-"), abs(imp))
            }
            if (cl < sma8) {
                imp = curr_inv[id] * impact_unit
                report[id] = report[id] sprintf("\n  [EXIT: SMA8 Brk] %s at $%.2f | Impact: %s$%.2f", $3, cl, (imp>=0?"+":"-"), abs(imp))
            }
        }
    }
    prev_cl = cl
}

END {
    total_wins = 0; total_trades = 0; total_profit = 0
    
    # Sort IDs for cleaner output
    n = asorti(start_iso, sorted_ids)
    
    for (i = 1; i <= n; i++) {
        id = sorted_ids[i]
        total_trades++
        if (realized_pnl[id] > 0) total_wins++
        total_profit += realized_pnl[id]

        print "=================================================================================="
        printf "TRADE AUDIT: %-10s | SYMBOL: %-5s | TOTAL REALIZED P&L: $%.2f\n", id, trade_to_symbol[id], realized_pnl[id]
        printf "PEAK (MFE): $%6.2f (%s) | LOW (MAE): $%6.2f (%s)\n", mfe[id], mfe_dt[id], mae[id], mae_dt[id]
        print "----------------------------------------------------------------------------------"
        print "TECHNICAL SIGNALS & P&L IMPACT (vs. your actual final exit):"
        if (report[id] == "") print "  No technical signals triggered during trade window."
        else print report[id]
        print "=================================================================================="
    }
    
    if (total_trades > 0) {
        print "\nOVERALL PORTFOLIO SUMMARY:"
        print "----------------------------------------------------------------------------------"
        printf "Total Trades: %d | Win Rate: %.1f%% | Total Net Profit: $%.2f\n", \
            total_trades, (total_wins/total_trades)*100, total_profit
    }
}