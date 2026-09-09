#!/usr/bin/env python3
"""
Parse every saved raw CBS "Scoring Preview" capture under
data/weekly_matchups/raw/{year}_week{N}.txt into its own canonical CSV at
data/weekly_matchups/{year}_week{N}.csv.

Workflow to add a new week's matchup:
  1. Ask Claude to capture this week's Scoring Preview page (see the
     module docstring in src/data_sources/weekly_matchup.py for the exact
     format/URL and capture procedure) and save it to
     data/weekly_matchups/raw/<year>_week<N>.txt.
  2. Run this script:
       python scripts/fetch_weekly_matchup.py
     It (re-)parses every raw file found under that directory -- safe to
     re-run any time (e.g. after re-capturing the same week for updated
     projections closer to kickoff).

Downstream: pages/8_Weekly_Matchup.py reads whichever {year}_week{N}.csv
files exist to populate its Week selector.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from src.data_sources.weekly_matchup import load_raw_file, matchup_to_rows

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "weekly_matchups", "raw")
OUTPUT_DIR = os.path.join(ROOT, "data", "weekly_matchups")
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")

FILENAME_RE = re.compile(r"^(\d{4})_week(\d+)\.txt$")


def main() -> None:
    if not os.path.isdir(RAW_DIR):
        print(f"No raw directory found at {RAW_DIR}")
        return

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    team_order = config.get("draft", {}).get("team_order")

    import pandas as pd

    found = sorted(f for f in os.listdir(RAW_DIR) if FILENAME_RE.match(f))
    if not found:
        print(f"No <year>_week<N>.txt files found in {RAW_DIR}")
        return

    for filename in found:
        m = FILENAME_RE.match(filename)
        year = int(m.group(1))
        raw_path = os.path.join(RAW_DIR, filename)
        matchup = load_raw_file(raw_path, year=year, team_order=team_order)
        if matchup.week != int(m.group(2)):
            print(f"  ⚠️ {filename}: filename says week {m.group(2)} but the page itself says week {matchup.week} -- using the page's own value")

        rows = matchup_to_rows(matchup)
        df = pd.DataFrame(rows)
        out_path = os.path.join(OUTPUT_DIR, f"{year}_week{matchup.week}.csv")
        df.to_csv(out_path, index=False)
        print(
            f"Wrote {out_path} ({len(df)} rows -- {matchup.away_team} @ {matchup.home_team}, "
            f"week {matchup.week})"
        )


if __name__ == "__main__":
    main()
