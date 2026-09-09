#!/usr/bin/env python3
"""
Parse all saved raw transaction-report files under
data/transactions/raw/ into the canonical CSV at
data/transactions/transactions.csv.

Workflow to refresh with the season's latest moves:
  1. Capture the current state of CBS's Transaction Report (see the
     module docstring in src/data_sources/transactions.py for the exact
     format, URL pattern, and capture workflow) and save/append to
     data/transactions/raw/<year>_raw.txt.
  2. Run this script:
       python scripts/fetch_transactions.py
     It picks up every *_raw.txt file in that folder automatically.

Downstream: src/roster_state.py replays the resulting CSV on top of the
draft-day snapshot (data/draft_state.json) to compute each team's
CURRENT roster -- see that module and pages/4_My_Roster.py /
pages/6_League_Rosters.py's "Current roster" / "As drafted" toggle.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_sources.transactions import discover_raw_files, parse_raw_files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "transactions", "raw")
OUTPUT_CSV = os.path.join(ROOT, "data", "transactions", "transactions.csv")


def main() -> None:
    paths_by_year = discover_raw_files(RAW_DIR)
    if not paths_by_year:
        print(f"No *_raw.txt files found in {RAW_DIR}")
        return

    df = parse_raw_files(paths_by_year)
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)

    print(f"Wrote {OUTPUT_CSV} ({len(df)} transactions across {len(paths_by_year)} years: {sorted(paths_by_year)})")
    by_type = df["txn_type"].value_counts().to_dict() if "txn_type" in df.columns else {}
    print(f"  By type: {by_type}")
    other = df[df["txn_type"] == "other"] if "txn_type" in df.columns else df.iloc[0:0]
    if len(other):
        print(f"  ⚠️ {len(other)} row(s) with unrecognized action text (txn_type='other') -- review these:")
        for _, row in other.iterrows():
            print(f"    {row['date']} {row['team']} {row['player_name']}: {row['action_text']!r}")


if __name__ == "__main__":
    main()
