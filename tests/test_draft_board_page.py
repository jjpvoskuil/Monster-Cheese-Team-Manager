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

    lineup_df = at.dataframe[0].value
    rb1_row = lineup_df[lineup_df["Slot"] == "RB 1"].iloc[0]
    assert rb1_row["Player"] == my_player

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
