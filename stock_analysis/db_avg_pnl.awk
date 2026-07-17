BEGIN { FS="," }
FNR==1 { next }
NF>=7 {
    gsub(/%/,"",$7)
    if ($7+0==$7) { sum+=$7; n++ }
}
ENDFILE {
    if (n>0) {
        avg = sum/n
        printf "%.4f\t%d\t%s\n", avg, n, FILENAME
    }
    sum=0; n=0
}
