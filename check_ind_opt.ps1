$pidFile = "logs\IND_Optimizer_pid.txt"
if (Test-Path $pidFile) { Get-Content $pidFile }
$proc = Get-Process -Id 49920 -ErrorAction SilentlyContinue
if ($proc) { "ALIVE PID=49920" } else { "DEAD PID=49920" }
"--- STATUS ---"
if (Test-Path "stock_analysis\IND_optimizer_status.txt") { Get-Content "stock_analysis\IND_optimizer_status.txt" }
"--- LOG TAIL ---"
$log = Get-ChildItem logs\IND_Optimizer_*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($log) { "LOG=$($log.FullName)"; Get-Content $log.FullName -Tail 8 }
