#!/usr/bin/env python3
"""
Parse all saved raw draft-results files under data/draft_history/raw/ into
the canonical draft-history CSV at data/draft_history/draft_history.csv.

Workflow for adding a new completed season:
  1. Capture that year's picks from the CBS draft-results page (see the
     module docstring in src/data_sources/draft_history.py for the exact
     format and the multi-draft-entry gotcha some seasons have) and save
     to data/draft_history/raw/<year>_raw.txt.
  2. Run this script:
       python scripts/fetch_draft_history.py
     It picks up every *_raw.txt file in that folder automatically --
     no need to list years on the command line.

Downstream: src/draft_tendencies.py reads the resulting CSV to compute
historical per-round/per-pick positional tendencies.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_sources.draft_history import discover_raw_files, parse_raw_files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "draft_history", "raw")
OUTPUT_CSV = os.path.join(ROOT, "data", "draft_history", "draft_history.csv")


def main() -> None:
    paths_by_year = discover_raw_files(RAW_DIR)
    if not paths_by_year:
        print(f"No *_raw.txt files found in {RAW_DIR}")
        return

    df = parse_raw_files(paths_by_year)
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)

    print(f"Wrote {OUTPUT_CSV} ({len(df)} picks across {len(paths_by_year)} years: {sorted(paths_by_year)})")
    skipped = int(df["is_skipped"].sum()) if "is_skipped" in df.columns else 0
    autopicks = int(df["is_auto_pick"].sum()) if "is_auto_pick" in df.columns else 0
    unknown_pos = int(df["position"].isna().sum()) if "position" in df.columns else 0
    print(f"  {skipped} skipped picks, {autopicks} auto-picks, {unknown_pos} picks with unrecognized position format")
    for year, path in sorted(paths_by_year.items()):
        n = len(df[df["year"] == year])
        print(f"  {year}: {n} picks ({os.path.basename(path)})")


if __name__ == "__main__":
    main()
