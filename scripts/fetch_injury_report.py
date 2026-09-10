#!/usr/bin/env python3
"""
Parse every saved raw CBS Player News capture under
data/injury_report/raw/ into one current snapshot:
data/injury_report/current.csv.

Workflow to refresh injury data:
  1. Ask Claude to capture CBS's Player News feed -- see
     data/injury_report/raw/2026_week1_all_pages.txt's header comment
     for the exact URL, capture procedure, and entry format
     src/data_sources/injury_report.py parses. Use the feed's own "All"
     link (all ~47 pages' worth of entries in one page) rather than
     capturing page 1 alone -- a single page only covers the last ~20
     minutes of news and can miss a real, still-current designation
     (this bit us 2026-09-10: Jakobi Meyers' Questionable status was a
     few pages deep). Save each capture as
     data/injury_report/raw/<year>_week<N>_<label>.txt (the label just
     needs to keep filenames unique across captures -- this script
     doesn't care about it beyond that).
  2. Run this script:
       python scripts/fetch_injury_report.py
     It re-parses every raw file found under that directory into one
     combined data/injury_report/current.csv -- safe to re-run any time.

UNLIKE the season-projection and waiver-wire fetchers, this is a LIVE
snapshot, not a stable per-week dataset: a player's designation can
change hour to hour as practice reports come in. Re-run the capture +
this script whenever fresher injury data is wanted (at minimum, before
setting a lineup or evaluating a trade/waiver move); there's no "current
week" concept here the way there is for the other data sources.

DEDUPLICATION: the same player can appear in more than one raw capture
(re-captures over time, or overlapping pages), and even within a single
capture of the full feed (a follow-up story bumps an older one further
down). This script keeps only the single most recent note per player,
using the parsed `age` string relative to each raw file's own capture
timestamp (from its header comment's "Captured: YYYY-MM-DD" line) --
NOT relative to when this script happens to run, since a raw file
captured days ago still says "11 mins ago" (as of ITS capture time, not
now). Two age formats show up (see src/data_sources/injury_report.py's
docstring): a relative "N mins/hours/hrs/days ago", resolved against
the raw file's capture date, and an absolute "<Month> <D>, <YYYY>
<H>:<MM> AM/PM ET" for older stories, which is parsed directly and
doesn't depend on the capture date at all. A raw file without a
parseable "Captured:" header falls back to treating its relative-age
entries as captured at the time this script runs, which is only
approximately correct but strictly better than crashing.

Downstream: src/injury_status.py loads data/injury_report/current.csv
and is the shared lookup every page uses.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.data_sources.injury_report import parse_player_news

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "injury_report", "raw")
OUTPUT_PATH = os.path.join(ROOT, "data", "injury_report", "current.csv")

RAW_MARKER = "===== RAW TEXT BELOW =====\n"
CAPTURED_RE = re.compile(r"^#\s*Captured:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
RELATIVE_AGE_RE = re.compile(r"^(\d+)\s+(min|mins|hour|hours|hr|hrs|day|days)\s+ago$")
ABSOLUTE_AGE_RE = re.compile(r"^([A-Za-z]+ \d{1,2}, \d{4} \d{1,2}:\d{2} (?:AM|PM)) ET$")


def _effective_time(age: str, captured_at: datetime) -> datetime:
    """Resolve a parsed InjuryNote.age string to an absolute timestamp
    for sorting -- see src/data_sources/injury_report.py's docstring for
    the two age formats this handles."""
    rel_match = RELATIVE_AGE_RE.match(age)
    if rel_match:
        n, unit = int(rel_match.group(1)), rel_match.group(2)
        if unit.startswith("hour") or unit.startswith("hr"):
            delta = timedelta(hours=n)
        elif unit.startswith("day"):
            delta = timedelta(days=n)
        else:
            delta = timedelta(minutes=n)
        return captured_at - delta

    abs_match = ABSOLUTE_AGE_RE.match(age)
    if abs_match:
        try:
            return datetime.strptime(abs_match.group(1), "%B %d, %Y %I:%M %p")
        except ValueError:
            pass

    return captured_at


def main() -> None:
    if not os.path.isdir(RAW_DIR):
        print(f"No raw directory found at {RAW_DIR}")
        return

    found = sorted(f for f in os.listdir(RAW_DIR) if f.endswith(".txt"))
    if not found:
        print(f"No .txt raw captures found in {RAW_DIR}")
        return

    all_rows: list[dict] = []
    for filename in found:
        raw_path = os.path.join(RAW_DIR, filename)
        full_text = open(raw_path, encoding="utf-8").read()
        captured_match = CAPTURED_RE.search(full_text)
        captured_at = (
            datetime.strptime(captured_match.group(1), "%Y-%m-%d")
            if captured_match else datetime.now()
        )
        text = full_text.split(RAW_MARKER, 1)[-1]
        for note in parse_player_news(text):
            effective_time = _effective_time(note.age, captured_at)
            all_rows.append({
                "name": note.name, "nfl_team": note.nfl_team or "", "designation": note.designation,
                "headline": note.headline, "note": note.note, "effective_time": effective_time,
                "source_file": filename,
            })
        print(f"Parsed {filename} (captured {captured_at:%Y-%m-%d}): {len(all_rows)} rows so far")

    if not all_rows:
        print("No parseable entries found across all raw files.")
        return

    df = pd.DataFrame(all_rows)
    df = df.sort_values("effective_time", ascending=False).drop_duplicates(subset="name", keep="first")
    df = df.sort_values(["name"]).reset_index(drop=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {OUTPUT_PATH} ({len(df)} unique players, from {len(found)} raw file(s))")


if __name__ == "__main__":
    main()
