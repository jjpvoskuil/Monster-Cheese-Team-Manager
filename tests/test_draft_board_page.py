"""
AppTest smoke tests for the Draft Board's clickable-grid pick logging and
the new My Roster page. These exercise real page code (not just the
underlying src/ functions, already covered elsewhere) end to end, the
same way prior sessions verified UI changes per SESSION_NOTES.md -- this
is the first time that verification is captured as a committed test
rather than an ad hoc run.

Must be entered via app.py (the multipage entrypoint) + switch_page(),
not AppTest.from_file() on a pages/*.py script directly -- Streamlit's
page registry (needed for st.page_link between pages) isn't attached to
a standalone page script, only to the app started from its real
entrypoint. See pages/1_Draft_Board.py <-> pages/4_My_Roster.py links.
"""

from __future__ import annotations

import json
import os

import pytest
from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")


@pytest.fixture(autouse=True)
def _clean_draft_state():
    """These tests log real picks against the live data/draft_state.json
    (same file the app itself reads/writes -- there's no test-only state
    file plumbed through the page yet). Save/restore it so running the
    test suite never clobbers an in-progress draft, and so re-running
    tests is deterministic."""
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


def _grid(at):
    return next(df for df in at.dataframe if df.key and df.key.startswith("player_grid_"))


def test_clicking_a_grid_row_drafts_for_whoever_is_on_the_clock():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/1_Draft_Board.py")
    at.run(timeout=60)
    assert not at.exception

    grid = _grid(at)
    top_player = grid.value.iloc[0]["Player"]

    at.session_state[grid.key] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    at.run(timeout=60)
    assert not at.exception

    with open(DRAFT_STATE_FILE) as f:
        state = json.load(f)
    assert len(state["picks"]) == 1
    pick = state["picks"][0]
    assert pick["player_name"] == top_player
    # Pick 1 in the real snake order (config/league_settings.yaml) goes to
    # the first team listed under draft.team_order, not Monster Cheese --
    # confirms the click registers to the team ON THE CLOCK, not always
    # "my" team.
    assert pick["team"] == "Mississippi Swamp Ass"

    # The grid's widget key must have advanced (player_grid_0 -> _1) so a
    # stale "row 0 selected" doesn't re-fire against next rerun's grid,
    # which now has one fewer available player at that same row position.
    new_grid = _grid(at)
    assert new_grid.key != grid.key


def test_clicking_a_tier_divider_row_does_not_log_a_phantom_pick():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/1_Draft_Board.py")
    at.run(timeout=60)

    # Filter to a single position so tier-divider rows are inserted.
    pos_multiselect = next(w for w in at.multiselect if w.label == "Position")
    pos_multiselect.select("RB").run(timeout=60)

    grid = _grid(at)
    # Row 0 is always the top-tier divider ("— Tier 1 —") once filtered to
    # one position -- add_tier_divider_rows() inserts it before the first
    # player of each tier, and tier 1 is always first.
    assert str(grid.value.iloc[0]["Player"]).startswith("— Tier")

    at.session_state[grid.key] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    at.run(timeout=60)
    assert not at.exception
    assert not os.path.exists(DRAFT_STATE_FILE)


def test_reset_draft_requires_confirmation_and_clears_state():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/1_Draft_Board.py")
    at.run(timeout=60)

    # Draft one pick first so there's something to reset.
    grid = _grid(at)
    at.session_state[grid.key] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    at.run(timeout=60)
    assert os.path.exists(DRAFT_STATE_FILE)

    reset_button = next(b for b in at.button if b.label == "Reset draft")
    assert reset_button.disabled  # checkbox not checked yet -- can't click a live pick away by accident

    confirm_checkbox = next(c for c in at.checkbox if c.key == "confirm_reset_draft")
    confirm_checkbox.check().run(timeout=60)

    reset_button = next(b for b in at.button if b.label == "Reset draft")
    assert not reset_button.disabled
    reset_button.click().run(timeout=60)
    assert not at.exception

    with open(DRAFT_STATE_FILE) as f:
        state = json.load(f)
    assert state["picks"] == []
    # Grid's selection-widget nonce must also reset, so the very next grid
    # render starts as a genuinely fresh, unselected widget rather than
    # carrying forward whatever key/selection state predates the reset.
    assert _grid(at).key == "player_grid_0"


def test_superflex_is_labeled_qb_flex_on_my_roster_page():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/4_My_Roster.py")
    at.run(timeout=60)
    assert not at.exception

    lineup_df = at.dataframe[0].value
    slots = list(lineup_df["Slot"])
    assert any(s.startswith("QB (Flex)") for s in slots)
    assert not any("SUPERFLEX" in s for s in slots)


def test_my_roster_page_fills_in_as_picks_are_logged():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/1_Draft_Board.py")
    at.run(timeout=60)

    # Draft 8 picks so it becomes Monster Cheese's turn (8th slot, round-1
    # snake order) and it gets a real roster entry.
    my_player = None
    for i in range(8):
        grid = _grid(at)
        if i == 7:
            my_player = grid.value.iloc[0]["Player"]
        at.session_state[grid.key] = {"selection": {"rows": [0], "columns": [], "cells": []}}
        at.run(timeout=60)
        assert not at.exception

    at.switch_page("pages/4_My_Roster.py")
    at.run(timeout=60)
    assert not at.exception

    # Don't assume WHICH slot the top-of-board player lands in -- that
    # depends on the player's real position plus the current
    # value/replacement-level config (e.g. flex_position_splits), which
    # this test shouldn't need to know or keep in sync with. Just confirm
    # the drafted player shows up in exactly one starting-lineup slot.
    lineup_df = at.dataframe[0].value
    matching_rows = lineup_df[lineup_df["Player"] == my_player]
    assert len(matching_rows) == 1

    # Sidebar's "picks by round" table on the Draft Board should show all
    # 8 picks, most recent first -- confirms the sidebar and the roster
    # page are reading the same live state.
    at.switch_page("pages/1_Draft_Board.py")
    at.run(timeout=60)
    picks_by_round = next(
        df for df in at.dataframe
        if list(df.value.columns) == ["Rd", "Pick", "Team", "Player", "Pos"]
    )
    assert len(picks_by_round.value) == 8
    assert picks_by_round.value.iloc[0]["Team"] == "Monster Cheese"


def _write_draft_state_directly(rounds_to_log):
    """Log picks straight through src.draft_state.DraftState against the
    real config/team order and save to the live draft_state.json, instead
    of clicking through the Draft Board grid -- much faster for tests that
    just need "N picks logged" and don't care about realistic value/need
    behavior (e.g. exercising round-deadline UI on My Roster)."""
    import yaml

    from src.draft_state import DraftState

    with open(os.path.join(ROOT, "config", "league_settings.yaml")) as f:
        config = yaml.safe_load(f)
    teams = config["draft"]["team_order"]
    ds = DraftState(
        teams=teams,
        rounds=config["draft"]["rounds"],
        my_team=config["league"]["team_name"],
        state_file=DRAFT_STATE_FILE,
        reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
    )
    for _ in range(rounds_to_log * len(teams)):
        # Every pick (mine included) is an RB filler -- leaves the K/DEF/
        # WR-TE/TE-mandatory draft-requirement categories entirely unmet
        # while still satisfying the RB-eligible categories, so the
        # round-20 warning/error banners below have something real to
        # report on.
        ds.log_pick_on_the_clock("Filler", position="RB")
    return ds, config


def test_my_roster_page_warns_near_round_20_with_unmet_requirements():
    ds, config = _write_draft_state_directly(rounds_to_log=18)
    current_round, _ = ds.round_and_slot_for_pick(ds.next_overall_pick)
    assert current_round == 19  # within the near-round-20 warning window

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/4_My_Roster.py")
    at.run(timeout=60)
    assert not at.exception

    assert len(at.warning) == 1
    assert "round 20" in at.warning[0].value.lower()
    assert not at.error


def test_my_roster_page_errors_once_round_20_deadline_has_passed():
    ds, config = _write_draft_state_directly(rounds_to_log=20)
    current_round, _ = ds.round_and_slot_for_pick(ds.next_overall_pick)
    assert current_round == 21  # past the round-20 deadline

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/4_My_Roster.py")
    at.run(timeout=60)
    assert not at.exception

    assert len(at.error) == 1
    assert "round 20" in at.error[0].value.lower()


def test_draft_board_shows_simulated_adp_column_and_league_strength_table():
    """Punch-list item #1: data/simulations/adp_2026.csv and
    team_points_2026.csv (committed, generated by
    scripts/simulate_draft.py -- see that script's module docstring) get
    picked up automatically, adding an "ADP" column to the main grid and
    a "Simulated league strength" table of each team's average points
    and rank."""
    adp_csv = os.path.join(ROOT, "data", "simulations", "adp_2026.csv")
    team_points_csv = os.path.join(ROOT, "data", "simulations", "team_points_2026.csv")
    assert os.path.exists(adp_csv), "run scripts/simulate_draft.py --adp-csv ... first (see its docstring)"
    assert os.path.exists(team_points_csv)

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/1_Draft_Board.py")
    at.run(timeout=60)
    assert not at.exception

    grid = _grid(at)
    assert "ADP" in grid.value.columns

    strength_df = next(
        df for df in at.dataframe
        if list(df.value.columns) == ["Rank", "Team", "Avg Pts", "Avg Finish", "Best Finish", "Worst Finish"]
    )
    assert len(strength_df.value) == 10  # one row per real league team
    assert set(strength_df.value["Team"]) == set(at.session_state.team_names)
    # Ranks are 1..N with no gaps/dupes, and #1 has the highest avg points.
    assert sorted(strength_df.value["Rank"]) == list(range(1, 11))
    top_row = strength_df.value[strength_df.value["Rank"] == 1].iloc[0]
    assert top_row["Avg Pts"] == strength_df.value["Avg Pts"].max()
