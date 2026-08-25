"""
CLI to (re)build data/projections/fantasypros_2026.csv.

Two modes:
  --live      Attempt a fresh fetch directly from fantasypros.com via
              requests + pandas.read_html. UNVERIFIED from this sandboxed
              session (no internet egress here) -- see fantasypros.py's
              module docstring. Should work from Streamlit Cloud or a
              normal machine if the page is server-rendered as suspected;
              if it raises complaining no table was found, the page turned
              out to need JS rendering and this flag won't work -- fall
              back to a fresh --from-capture instead.
  --from-capture  Parse a saved JSON capture (row-array table data
                  extracted via Claude in Chrome's javascript_tool DOM
                  extraction -- NOT WebFetch, which fabricated wrong data
                  for this exact site earlier in this project, see
                  SESSION_NOTES.md). See
                  data/projections/raw/fantasypros_2026_raw.json for the
                  format this session used to seed the initial data.

Remember: FantasyPros' free tier caps every position at the top 10 players
regardless of fetch method -- this will always be a partial source.

Usage:
    python scripts/fetch_fantasypros.py --live
    python scripts/fetch_fantasypros.py --from-capture data/projections/raw/fantasypros_2026_raw.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_sources.fantasypros import fetch_all, load_seed_json


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="attempt a live fetch from fantasypros.com")
    ap.add_argument("--from-capture", metavar="PATH", help="parse a saved JSON capture instead of fetching live")
    ap.add_argument("--output", default="data/projections/fantasypros_2026.csv", help="output CSV path")
    args = ap.parse_args()

    if args.live == bool(args.from_capture):
        ap.error("pass exactly one of --live or --from-capture")

    df = fetch_all() if args.live else load_seed_json(args.from_capture)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path} (note: FantasyPros free tier caps at 10/position)")


if __name__ == "__main__":
    main()
