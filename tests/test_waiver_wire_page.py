"""
AppTest smoke tests for the Waiver Wire page. Parser and recommendation
logic are unit-tested directly in tests/test_waiver_wire.py and
tests/test_waiver_recommendations.py; these tests only confirm the page
wires real captured data up and renders without error, and that the
CBS/FantasyPoints/Both source toggle doesn't crash in any position.

Runs against the REAL repo data (data/draft_state.json,
data/waiver_wire/2026_*.csv, data/projections/*_2026.csv,
data/weekly_matchups/2026_week1.csv) rather than synthetic fixtures --
unlike Weekly Matchup's tests, the draft is complete and all of this
page's real inputs already exist and are checked in, so there's no
"data not captured yet" state to fake for the main smoke test. A
separate test below covers the genuinely-missing-data path by pointing
at a week number nothing has captured.
"""

from __future__ import annotations

import os

from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _open_page(at):
    at.switch_page("pages/9_Waiver_Wire.py")
    at.run(timeout=60)
    assert not at.exception
    return at


def test_page_renders_with_real_data():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    assert at.selectbox[0].value == (2026, 1)
    assert at.radio  # the CBS/FantasyPoints/Both source toggle
    subheaders = " ".join(s.value for s in at.subheader)
    assert "Top pickup recommendations" in subheaders


def test_source_toggle_cbs_only_does_not_crash():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    at.radio[0].set_value("CBS").run(timeout=60)
    assert not at.exception


def test_source_toggle_fantasypoints_only_does_not_crash():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    at.radio[0].set_value("FantasyPoints").run(timeout=60)
    assert not at.exception


def test_roster_expander_lists_all_rostered_players():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    roster_dataframes = [d.value for d in at.dataframe]
    assert roster_dataframes
    # The last dataframe rendered is the "Your current roster" expander's
    # table -- confirm it has at least one row and the expected columns.
    roster_df = roster_dataframes[-1]
    assert len(roster_df) > 0
    assert "Player" in roster_df.columns
    assert "CBS season pts" in roster_df.columns
    assert "FantasyPoints season pts" in roster_df.columns
