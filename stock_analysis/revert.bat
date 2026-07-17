cd stock_analysis
git restore --source=HEAD~1 portfolio_audit.awk
git add portfolio_audit.awk
git commit -m "reverting file"
cd ..
