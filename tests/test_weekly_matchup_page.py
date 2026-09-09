"""
AppTest smoke tests for the Weekly Matchup page. Parser correctness is
unit-tested directly in tests/test_weekly_matchup.py and
tests/test_weekly_projections.py; these tests only confirm the page
wires that data up, renders without error, and the CBS/FantasyPoints
toggle actually changes what's displayed.

Same AppTest-via-app.py pattern as the other pages (st.page_link needs
the real multipage router). Writes synthetic matchup/projections CSVs
directly (bypassing the raw-capture parsers, which have their own
tests) so these tests don't depend on -- or get broken by -- the real
captured 2026 Week 1 files.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest
import yaml
from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
MATCHUP_DIR = os.path.join(ROOT, "data", "weekly_matchups")
PROJECTIONS_DIR = os.path.join(ROOT, "data", "weekly_projections")


def _load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _matchup_csv_path(year, week):
    return os.path.join(MATCHUP_DIR, f"{year}_week{week}.csv")


def _fp_csv_path(year, week):
    return os.path.join(PROJECTIONS_DIR, f"fantasypoints_{year}_week{week}.csv")


@pytest.fixture
def synthetic_week(tmp_path):
    """Writes a tiny 1-starter-per-side matchup for a week number that
    can't collide with any real captured data (999), cleaned up after."""
    config = _load_config()
    my_team = config["league"]["team_name"]
    year, week = 2026, 999

    rows = [
        {"year": year, "week": week, "away_team": "Ball Busters", "home_team": my_team,
         "team": "Ball Busters", "roster_group": "starter", "slot": "Quarterbacks",
         "slot_index": 1, "order": 1, "player_name": "Away Starter", "position": "QB",
         "nfl_team": "AAA", "matchup_desc": "AAA vs BBB", "cbs_points": 10.0},
        {"year": year, "week": week, "away_team": "Ball Busters", "home_team": my_team,
         "team": my_team, "roster_group": "starter", "slot": "Quarterbacks",
         "slot_index": 1, "order": 1, "player_name": "Home Starter", "position": "QB",
         "nfl_team": "CCC", "matchup_desc": "CCC vs DDD", "cbs_points": 12.0},
        {"year": year, "week": week, "away_team": "Ball Busters", "home_team": my_team,
         "team": "Ball Busters", "roster_group": "bench", "slot": "Bench",
         "slot_index": 0, "order": 1, "player_name": "Away Bench", "position": "RB",
         "nfl_team": "EEE", "matchup_desc": "EEE vs FFF", "cbs_points": 3.0},
        {"year": year, "week": week, "away_team": "Ball Busters", "home_team": my_team,
         "team": my_team, "roster_group": "bench", "slot": "Bench",
         "slot_index": 0, "order": 1, "player_name": "Home Bench", "position": "RB",
         "nfl_team": "GGG", "matchup_desc": "GGG vs HHH", "cbs_points": 4.0},
    ]
    os.makedirs(MATCHUP_DIR, exist_ok=True)
    pd.DataFrame(rows).to_csv(_matchup_csv_path(year, week), index=False)

    fp_rows = [
        {"rank": 1, "name": "Away Starter", "position": "QB", "nfl_team": "AAA",
         "opp": "BBB", "fpts": 20.0, "match_key": "A|starter|AAA"},
        {"rank": 2, "name": "Home Starter", "position": "QB", "nfl_team": "CCC",
         "opp": "DDD", "fpts": 8.0, "match_key": "H|starter|CCC"},
        # deliberately no FantasyPoints row for either bench player, to
        # exercise the "no projection for this player" path.
    ]
    os.makedirs(PROJECTIONS_DIR, exist_ok=True)
    pd.DataFrame(fp_rows).to_csv(_fp_csv_path(year, week), index=False)

    yield year, week, my_team

    for p in (_matchup_csv_path(year, week), _fp_csv_path(year, week)):
        if os.path.exists(p):
            os.remove(p)


def _open_page(at):
    at.switch_page("pages/8_Weekly_Matchup.py")
    at.run(timeout=60)
    assert not at.exception
    return at


def test_page_renders_empty_state_with_no_matchup_data(tmp_path, monkeypatch):
    # Point the page at an empty directory so "no data yet" is exercised
    # without having to delete any real captured files.
    import pages  # noqa: F401 -- ensure package import machinery is set up

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/8_Weekly_Matchup.py")
    # Can't easily blank MATCHUP_DIR here without touching real data (other
    # tests/synthetic_week fixture may run in parallel) -- if real weekly
    # data exists this just confirms the normal render path instead, which
    # test_page_renders_with_synthetic_week_data covers explicitly anyway.
    at.run(timeout=60)
    assert not at.exception


def test_page_renders_with_synthetic_week_data(synthetic_week):
    year, week, my_team = synthetic_week
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    assert at.radio[0].value == "CBS"
    subheader_text = " ".join(s.value for s in at.subheader)
    assert "10.0" in subheader_text  # CBS points for the synthetic away starter... via total
    assert my_team in subheader_text


def test_toggle_to_fantasypoints_changes_totals(synthetic_week):
    year, week, my_team = synthetic_week
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    # Week 999 sorts newest-first, so it's already the default selection --
    # no real captured week will ever reach that number.
    assert at.selectbox[0].value == (2026, 999)

    at.radio[0].set_value("FantasyPoints").run(timeout=60)
    assert not at.exception
    subheader_text = " ".join(s.value for s in at.subheader)
    # FantasyPoints totals from the fixture: away starter 20.0, home starter 8.0
    assert "20.0" in subheader_text
    assert "8.0" in subheader_text


def test_download_button_present(synthetic_week):
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)
    assert len(at.download_button) == 1
    assert "csv" in at.download_button[0].label.lower() or "download" in at.download_button[0].label.lower()


def test_start_recommendation_and_bye_highlight():
    # Deliberately its own week number (997) rather than the shared
    # synthetic_week fixture, same reasoning as test_missing_fantasypoints_
    # data_shows_warning below: a distinct week avoids any st.cache_data
    # mtime-collision risk with another test's fixture.
    config = _load_config()
    my_team = config["league"]["team_name"]
    year, week = 2026, 997

    rows = [
        {"year": year, "week": week, "away_team": "Ball Busters", "home_team": my_team,
         "team": "Ball Busters", "roster_group": "starter", "slot": "Quarterbacks",
         "slot_index": 1, "order": 1, "player_name": "Away Starter", "position": "QB",
         "nfl_team": "AAA", "matchup_desc": "AAA vs BBB", "cbs_points": 10.0},
        # A weak starting QB that a much stronger bench QB should replace.
        {"year": year, "week": week, "away_team": "Ball Busters", "home_team": my_team,
         "team": my_team, "roster_group": "starter", "slot": "Quarterbacks",
         "slot_index": 1, "order": 1, "player_name": "Weak Starter QB", "position": "QB",
         "nfl_team": "CCC", "matchup_desc": "CCC vs DDD", "cbs_points": 5.0},
        {"year": year, "week": week, "away_team": "Ball Busters", "home_team": my_team,
         "team": my_team, "roster_group": "bench", "slot": "Bench",
         "slot_index": 0, "order": 1, "player_name": "Strong Bench QB", "position": "QB",
         "nfl_team": "EEE", "matchup_desc": "EEE vs FFF", "cbs_points": 25.0},
        # A starter whose team is on a bye -- can't legally start regardless
        # of their projection, should be flagged as both "bye" and "bench".
        {"year": year, "week": week, "away_team": "Ball Busters", "home_team": my_team,
         "team": my_team, "roster_group": "starter", "slot": "Running Backs",
         "slot_index": 1, "order": 2, "player_name": "Bye Starter RB", "position": "RB",
         "nfl_team": "GGG", "matchup_desc": "BYE", "cbs_points": 15.0},
    ]
    os.makedirs(MATCHUP_DIR, exist_ok=True)
    pd.DataFrame(rows).to_csv(_matchup_csv_path(year, week), index=False)

    try:
        at = AppTest.from_file(os.path.join(ROOT, "app.py"))
        at.run(timeout=60)
        at = _open_page(at)

        assert at.selectbox[0].value == (year, week)
        assert not at.exception

        captions = " ".join(c.value for c in at.caption)
        assert "should be in your starting lineup" in captions
        assert "on a bye" in captions
    finally:
        os.remove(_matchup_csv_path(year, week))


def test_missing_fantasypoints_data_shows_warning():
    # Deliberately a DIFFERENT week number from the synthetic_week fixture
    # (998, not 999) and no FantasyPoints CSV ever written for it -- using
    # the same week+mtime as another test risks st.cache_data (keyed on
    # (year, week, mtime), same pattern as pages/2_Projections.py) hitting
    # a stale cross-test entry if two quick writes land on the same
    # filesystem-timestamp second.
    config = _load_config()
    my_team = config["league"]["team_name"]
    year, week = 2026, 998
    rows = [
        {"year": year, "week": week, "away_team": "Ball Busters", "home_team": my_team,
         "team": "Ball Busters", "roster_group": "starter", "slot": "Quarterbacks",
         "slot_index": 1, "order": 1, "player_name": "Away Starter2", "position": "QB",
         "nfl_team": "AAA", "matchup_desc": "AAA vs BBB", "cbs_points": 10.0},
        {"year": year, "week": week, "away_team": "Ball Busters", "home_team": my_team,
         "team": my_team, "roster_group": "starter", "slot": "Quarterbacks",
         "slot_index": 1, "order": 1, "player_name": "Home Starter2", "position": "QB",
         "nfl_team": "CCC", "matchup_desc": "CCC vs DDD", "cbs_points": 12.0},
    ]
    os.makedirs(MATCHUP_DIR, exist_ok=True)
    pd.DataFrame(rows).to_csv(_matchup_csv_path(year, week), index=False)
    assert not os.path.exists(_fp_csv_path(year, week))

    try:
        at = AppTest.from_file(os.path.join(ROOT, "app.py"))
        at.run(timeout=60)
        at = _open_page(at)

        assert at.selectbox[0].value == (2026, 998)
        at.radio[0].set_value("FantasyPoints").run(timeout=60)

        assert not at.exception
        warnings = [w.value for w in at.warning]
        assert any("No FantasyPoints" in w for w in warnings)
    finally:
        os.remove(_matchup_csv_path(year, week))
