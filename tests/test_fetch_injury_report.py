"""
Unit tests for scripts/fetch_injury_report.py's `_effective_time` helper
-- the piece that turns a parsed InjuryNote.age string into an absolute
timestamp for dedup/sorting. See that script's module docstring and
src/data_sources/injury_report.py's docstring for the two age formats
handled here (relative "N mins/hours/hrs/days ago" vs. absolute
"<Month> <D>, <YYYY> <H>:<MM> AM/PM ET").
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# scripts/ isn't a package -- load the module directly by path, same
# approach this script's own sys.path.insert dance is standing in for.
_spec = importlib.util.spec_from_file_location(
    "fetch_injury_report", os.path.join(ROOT, "scripts", "fetch_injury_report.py")
)
fetch_injury_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_injury_report)

_effective_time = fetch_injury_report._effective_time

CAPTURED_AT = datetime(2026, 9, 10, 0, 0, 0)


def test_relative_minutes_and_hours():
    assert _effective_time("40 mins ago", CAPTURED_AT) == datetime(2026, 9, 9, 23, 20, 0)
    assert _effective_time("2 hours ago", CAPTURED_AT) == datetime(2026, 9, 9, 22, 0, 0)


def test_relative_abbreviated_hours():
    # "hr"/"hrs" -- the format most entries beyond the first page or so
    # actually use, which the original AGE_VALUE_RE never had to handle.
    assert _effective_time("4 hrs ago", CAPTURED_AT) == datetime(2026, 9, 9, 20, 0, 0)
    assert _effective_time("1 hr ago", CAPTURED_AT) == datetime(2026, 9, 9, 23, 0, 0)


def test_relative_days():
    assert _effective_time("2 days ago", CAPTURED_AT) == datetime(2026, 9, 8, 0, 0, 0)


def test_absolute_dated_age_parsed_directly_ignoring_captured_at():
    # An absolute age doesn't depend on the raw file's capture date at
    # all -- it's already a full timestamp.
    result = _effective_time("August 31, 2026 7:43 PM ET", CAPTURED_AT)
    assert result == datetime(2026, 8, 31, 19, 43, 0)


def test_unparseable_age_falls_back_to_captured_at():
    assert _effective_time("some day", CAPTURED_AT) == CAPTURED_AT


def test_more_recent_relative_age_sorts_after_older_absolute_age():
    # This is the property the dedup in main() actually relies on: a
    # same-day relative-age entry must resolve to something later than
    # a days-old absolute-dated entry for the same player.
    recent = _effective_time("4 hrs ago", CAPTURED_AT)
    older = _effective_time("September 2, 2026 9:41 AM ET", CAPTURED_AT)
    assert recent > older
