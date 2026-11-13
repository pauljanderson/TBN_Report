# Used only by run_honest.py preflight: print the engine argv and exit before any work.
import sys
if sys.argv and sys.argv[0].replace('\\','/').endswith('stock_analysis/rocket_tbn.py'):
    print('ARGS:', ' '.join(sys.argv[1:]), flush=True)
    raise SystemExit(0)
