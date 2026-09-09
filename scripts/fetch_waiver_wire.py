#!/usr/bin/env python3
"""
Parse every saved raw CBS free-agent capture under data/waiver_wire/raw/
into two canonical CSVs per year: data/waiver_wire/{year}_week{N}.csv
(this week's free-agent pool, for filling a bye-week starting-lineup
gap) and data/waiver_wire/{year}_restofseason.csv (the season-long pool,
for "is this free agent better than someone already on my roster").

Workflow to add/refresh a week's waiver-wire data:
  1. Ask Claude to capture this week's CBS free-agent tables (see the
     module docstring in src/data_sources/waiver_wire.py for the exact
     format) -- 3 captures per timeframe (ALL OFFENSE, K, DST), 2
     timeframes (Week N (Proj), Rest of Season (Proj)) = 6 raw files:
       data/waiver_wire/raw/<year>_week<N>_offense.txt
       data/waiver_wire/raw/<year>_week<N>_k.txt
       data/waiver_wire/raw/<year>_week<N>_dst.txt
       data/waiver_wire/raw/<year>_restofseason_offense.txt
       data/waiver_wire/raw/<year>_restofseason_k.txt
       data/waiver_wire/raw/<year>_restofseason_dst.txt
     Only the Week N trio needs re-capturing most weeks -- Rest of
     Season only needs a refresh occasionally (early-season injuries/
     depth-chart moves shift it slowly; it doesn't reset weekly the way
     the Week N pool does once that week's games are locked).

     CAPTURE PROCEDURE (2026-09-09 session's working method -- CBS's
     stats-main page is a client-side SPA that does NOT reliably apply a
     filter combination reached by navigating directly to a pre-composed
     deep-link URL; state must be reached by sequential UI interaction
     on an already-loaded page):
       a. Load https://<league>.football.cbssports.com/stats/stats-main
          with PLAYER STATUS already on FREE AGENTS (the default for a
          fresh load of this page in past sessions -- confirm via
          get_page_text if starting fresh).
       b. Set the TIMEFRAME <select> (the 4th <select> on the page in
          this session's DOM order -- verify via
          document.querySelectorAll('select') if CBS's layout ever
          changes) to the desired value and dispatch a change event:
          `document.createEvent('HTMLEvents')` + `initEvent('change',
          true, true)` + `dispatchEvent` -- `new Event(...)` throws
          "Event is not a constructor" in this execution context.
       c. Changing TIMEFRAME can silently reset PLAYER STATUS back to
          "Show My Team" -- immediately re-click the `<a href="/fa">`
          link to restore Free Agents, confirmed via get_page_text
          before capturing (header should read "FREE AGENT(S) ... CBS
          AVERAGE PROJECTIONS").
       d. Click the position link (`<a href="/QB">`,`/RB`,`/TE`,
          `/WR-TE`,`/K`,`/DST`, or leave on the default ALL OFFENSE) --
          NOTE this does not exist as one combined link for "ALL
          OFFENSE"; that's simply the page's own default position
          grouping when no individual position link has been clicked.
       e. get_page_text and save (see src/data_sources/waiver_wire.py's
          docstring for the exact row format to preserve, or save
          verbatim). The Rest of Season / ALL OFFENSE combination is
          large (1,700+ rows) -- appending `?print_rows=9999` to the URL
          bypasses CBS's ~90-row-per-page default BEFORE doing the
          above UI steps gets the full listing in one capture, though
          this print_rows value does NOT persist across a later
          UI-driven filter change (re-add it, or accept the shorter
          default-paginated list -- for Week N specifically the default
          first page already covers every free agent with real
          value, see that raw file's own header comment).
  2. Run this script:
       python scripts/fetch_waiver_wire.py
     It (re-)parses every raw file found under that directory and
     regroups the 3 position-group files per (year, timeframe) into one
     combined CSV -- safe to re-run any time.

Downstream: pages/9_Waiver_Wire.py reads whichever {year}_week{N}.csv /
{year}_restofseason.csv files exist.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.data_sources.waiver_wire import candidates_to_rows, load_raw_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "waiver_wire", "raw")
OUTPUT_DIR = os.path.join(ROOT, "data", "waiver_wire")

FILENAME_RE = re.compile(r"^(\d{4})_(week\d+|restofseason)_(offense|k|dst)\.txt$")


def main() -> None:
    if not os.path.isdir(RAW_DIR):
        print(f"No raw directory found at {RAW_DIR}")
        return

    found = sorted(f for f in os.listdir(RAW_DIR) if FILENAME_RE.match(f))
    if not found:
        print(f"No <year>_<week<N>|restofseason>_<offense|k|dst>.txt files found in {RAW_DIR}")
        return

    # Group the 3 position-group files (offense/k/dst) that share a
    # (year, timeframe) into one combined output CSV.
    groups: dict[tuple[str, str], list[str]] = {}
    for filename in found:
        m = FILENAME_RE.match(filename)
        year, timeframe, group = m.group(1), m.group(2), m.group(3)
        groups.setdefault((year, timeframe), []).append(filename)

    for (year, timeframe), filenames in sorted(groups.items()):
        all_rows = []
        for filename in sorted(filenames):
            raw_path = os.path.join(RAW_DIR, filename)
            candidates = load_raw_file(raw_path)
            all_rows.extend(candidates_to_rows(candidates, year=int(year), timeframe=timeframe))

        df = pd.DataFrame(all_rows).sort_values("fpts", ascending=False).reset_index(drop=True)
        out_path = os.path.join(OUTPUT_DIR, f"{year}_{timeframe}.csv")
        df.to_csv(out_path, index=False)
        groups_captured = ", ".join(sorted(f.rsplit("_", 1)[1].replace(".txt", "") for f in filenames))
        print(f"Wrote {out_path} ({len(df)} rows -- from {groups_captured})")


if __name__ == "__main__":
    main()
