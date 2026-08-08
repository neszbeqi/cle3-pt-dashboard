"""
fetch_scc.py -- run SCC scrape as subprocess, write result via fetch_all(out_file=...).
The write happens INSIDE sync_playwright() context to avoid Windows Playwright teardown killing process.
"""
import sys, json, os

def main():
    app_dir  = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    out_file = os.path.join(app_dir, ".scc_result_tmp.json")
    sys.path.insert(0, app_dir)
    from scc import fetch_all
    fetch_all(out_file=out_file)

if __name__ == "__main__":
    main()
