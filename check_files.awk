# check_files.awk
BEGIN { FS="," }
FNR == 1 { print "ARGIND: " ARGIND " | Filename: " FILENAME " | First Row: " $1 "," $2 "," $3 }