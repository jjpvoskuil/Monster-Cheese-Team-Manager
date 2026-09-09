#!/usr/bin/env python3
"""
Parse every saved raw FantasyPoints "Weekly Projections" capture under
data/weekly_projections/raw/fantasypoints/{year}_week{N}_all.txt into its
own canonical CSV at data/weekly_projections/fantasypoints_{year}_week{N}.csv.

Workflow to add a new week: ask Claude to capture that week's FantasyPoints
Weekly Projections page (see src/data_sources/weekly_projections.py's
module docstring for the exact capture procedure) and save it to
data/weekly_projections/raw/fantasypoints/<year>_week<N>_all.txt, then run:
    python scripts/fetch_weekly_projections.py
Safe to re-run any time.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.data_sources.weekly_projections import load_raw_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "weekly_projections", "raw", "fantasypoints")
OUTPUT_DIR = os.path.join(ROOT, "data", "weekly_projections")

FILENAME_RE = re.compile(r"^(\d{4})_week(\d+)_all\.txt$")


def main() -> None:
    if not os.path.isdir(RAW_DIR):
        print(f"No raw directory found at {RAW_DIR}")
        return

    found = sorted(f for f in os.listdir(RAW_DIR) if FILENAME_RE.match(f))
    if not found:
        print(f"No <year>_week<N>_all.txt files found in {RAW_DIR}")
        return

    for filename in found:
        m = FILENAME_RE.match(filename)
        year, week = m.group(1), m.group(2)
        raw_path = os.path.join(RAW_DIR, filename)
        rows = load_raw_file(raw_path)
        df = pd.DataFrame(rows)
        out_path = os.path.join(OUTPUT_DIR, f"fantasypoints_{year}_week{week}.csv")
        df.to_csv(out_path, index=False)
        print(f"Wrote {out_path} ({len(df)} players)")


if __name__ == "__main__":
    main()
