"""
AppTest smoke tests for the League Rosters page (punch-list item #2):
"Create a page that shows the entire roster of each team in the league
that fills as we are drafting ... add a column to each roster to who the
project points for all the players and the total for each team. Have a
breakdown of total points for the roster and a second for the projected
starting line up for each team."

Same AppTest-via-app.py pattern as tests/test_draft_board_page.py (see
that file's module docstring for why: st.page_link needs the real
multipage router, not AppTest.from_file() on a pages/*.py script
directly), and the same save/restore fixture for the live
data/draft_state.json.
"""

from __future__ import annotations

import os

import pytest
import yaml
from streamlit.testing.v1 import AppTest

from src.draft_state import DraftState

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")


@pytest.fixture(autouse=True)
def _clean_draft_state():
    backup = None
    if os.path.exists(DRAFT_STATE_FILE):
        with open(DRAFT_STATE_FILE) as f:
            backup = f.read()
        os.remove(DRAFT_STATE_FILE)
    yield
    if os.path.exists(DRAFT_STATE_FILE):
        os.remove(DRAFT_STATE_FILE)
    if backup is not None:
        with open(DRAFT_STATE_FILE, "w") as f:
            f.write(backup)


def _load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _log_picks(rounds_to_log: int) -> tuple[DraftState, dict]:
    """Log picks straight through DraftState (fast, no grid-clicking)
    against the real config/team order, same helper style as
    test_draft_board_page.py's _write_draft_state_directly. Every pick is
    an RB filler -- fine here since these tests only care about pick
    counts and points plumbing, not realistic roster construction."""
    config = _load_config()
    teams = config["draft"]["team_order"]
    ds = DraftState(
        teams=teams,
        rounds=config["draft"]["rounds"],
        my_team=config["league"]["team_name"],
        state_file=DRAFT_STATE_FILE,
        reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
    )
    for _ in range(rounds_to_log * len(teams)):
        ds.log_pick_on_the_clock("Filler", position="RB")
    return ds, config


def _open_page(at):
    at.switch_page("pages/6_League_Rosters.py")
    at.run(timeout=60)
    assert not at.exception
    return at


def test_league_rosters_page_renders_with_no_picks_logged():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    config = _load_config()
    teams = config["draft"]["team_order"]

    summary_df = at.dataframe[0].value
    assert len(summary_df) == len(teams)
    assert set(summary_df["Picks"]) == {0}
    assert set(summary_df["Roster Pts"]) == {0.0}
    assert set(summary_df["Starting Lineup Pts"]) == {0.0}


def test_league_rosters_page_fills_in_as_picks_are_logged():
    ds, config = _log_picks(rounds_to_log=2)  # 2 full rounds -- everyone has picks

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    my_team = config["league"]["team_name"]
    summary_df = at.dataframe[0].value
    # Strip the "🎯 " prefix used to mark my own team in the summary table.
    row = summary_df[summary_df["Team"].str.endswith(my_team)].iloc[0]
    assert row["Picks"] == 2

    # "Filler" isn't a real player in any projections source, so points
    # for it come back as 0 and it should show up in the missing-
    # projection caption on the per-team expander, not silently vanish.
    body_text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Filler" in body_text


def test_league_rosters_page_flags_players_missing_from_projections():
    _log_picks(rounds_to_log=1)

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    captions = [c.value for c in at.caption]
    assert any("No projection found for" in c and "Filler" in c for c in captions)


def test_league_rosters_page_totals_are_zero_for_an_all_filler_roster():
    """Every logged pick is "Filler" (position RB, not in any real
    projections source) -- both Roster Pts and Starting Lineup Pts for
    every team should come back exactly 0, confirming the page doesn't
    silently substitute some other player's points for an unmatched name."""
    _log_picks(rounds_to_log=3)

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    summary_df = at.dataframe[0].value
    assert (summary_df["Roster Pts"] == 0.0).all()
    assert (summary_df["Starting Lineup Pts"] == 0.0).all()
    assert (summary_df["Picks"] == 3).all()


def test_league_rosters_page_per_team_expander_shows_proj_pts_column():
    _log_picks(rounds_to_log=1)

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    # Summary table is dataframe[0]; per-team roster grids follow it, one
    # per team with at least one pick.
    per_team_grids = at.dataframe[1:]
    assert len(per_team_grids) >= 1
    for grid in per_team_grids:
        assert "Proj Pts" in grid.value.columns
        assert "Player" in grid.value.columns
