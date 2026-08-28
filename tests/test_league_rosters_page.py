"""
AppTest smoke tests for the League Rosters page (punch-list item #2):
"Create a page that shows the entire roster of each team in the league
that fills as we are drafting ... add a column to each roster to who the
project points for all the players and the total for each team. Have a
breakdown of total points for the roster and a second for the projected
starting line up for each team." Layout (2026-08-28) matches the league
manager's own spreadsheet mockup: one Roster Position / Player / Proj
Pts table per team, capped with Starting Lineup Pts / Bench Points /
Total Team Points summary rows.

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
    counts and points plumbing, not realistic roster construction. RB is
    eligible for the dedicated RB slot (fewest eligible positions, so
    src.roster_needs.assign_roster_slots fills it before any flex slot),
    so up to `starters`'s RB count worth of fillers land in the Starting
    Lineup section, not the bench."""
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
    assert set(summary_df["Starting Lineup Pts"]) == {0.0}
    assert set(summary_df["Bench Points"]) == {0.0}
    assert set(summary_df["Total Team Points"]) == {0.0}

    # Every starter slot still gets a row even with nothing drafted --
    # matches the spreadsheet mockup's per-slot layout, empty or not.
    first_team_table = at.dataframe[1].value
    assert "Roster Position" in first_team_table.columns
    assert "— empty —" in first_team_table["Player"].values
    assert "Starting Lineup Pts" in first_team_table["Roster Position"].values
    assert "Bench Points" in first_team_table["Roster Position"].values
    assert "Total Team Points" in first_team_table["Roster Position"].values


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
    # Total Team Points must always equal Starting Lineup + Bench, since
    # every drafted pick lands in exactly one of those two buckets.
    assert row["Total Team Points"] == round(row["Starting Lineup Pts"] + row["Bench Points"], 1)

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
    projections source) -- Starting Lineup Pts, Bench Points, and Total
    Team Points should all come back exactly 0 for every team, confirming
    the page doesn't silently substitute some other player's points for
    an unmatched name."""
    _log_picks(rounds_to_log=3)

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    summary_df = at.dataframe[0].value
    assert (summary_df["Starting Lineup Pts"] == 0.0).all()
    assert (summary_df["Bench Points"] == 0.0).all()
    assert (summary_df["Total Team Points"] == 0.0).all()
    assert (summary_df["Picks"] == 3).all()


def test_league_rosters_page_per_team_table_has_roster_position_and_player_columns():
    _log_picks(rounds_to_log=1)

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    # Summary table is dataframe[0]; one per-team roster table follows
    # for every team (even those with zero picks, since starter slots
    # always render).
    config = _load_config()
    teams = config["draft"]["team_order"]
    per_team_tables = at.dataframe[1:]
    assert len(per_team_tables) == len(teams)
    for table in per_team_tables:
        cols = table.value.columns
        assert "Roster Position" in cols
        assert "Player" in cols
        assert "Proj Pts" in cols
