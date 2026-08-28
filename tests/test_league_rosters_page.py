"""
AppTest smoke tests for the League Rosters page (punch-list item #2).
The row-building/point-summing logic itself is unit-tested directly in
tests/test_league_grid.py (no Streamlit needed there) -- these tests
only confirm the page wires that logic up and renders without error,
via the raw HTML the page emits with st.markdown(unsafe_allow_html=True)
(there's no st.dataframe here to introspect -- the single wide grid is a
hand-built HTML table, see pages/6_League_Rosters.py's docstring for why).

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


def _grid_html(at) -> str:
    # render_grid_html's output is the 2nd st.markdown call (the 1st is
    # the injected <style> block).
    markdowns = [m.value for m in at.markdown]
    grid = next(m for m in markdowns if "league-grid" in m and "<table" in m)
    return grid


def test_league_rosters_page_renders_with_no_picks_logged():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    config = _load_config()
    teams = config["draft"]["team_order"]

    grid_html = _grid_html(at)
    for team in teams:
        assert team in grid_html
    assert "Roster Position" in grid_html
    assert "Starters" in grid_html
    assert "Starting Lineup Pts" in grid_html
    assert "Bench Points" in grid_html
    assert "Total Team Points" in grid_html
    # No picks logged -- every starter slot shows the empty-slot dash.
    assert "empty" in grid_html


def test_league_rosters_page_fills_in_as_picks_are_logged():
    ds, config = _log_picks(rounds_to_log=2)  # 2 full rounds -- everyone has picks

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    grid_html = _grid_html(at)
    # "Filler" isn't a real player in any projections source, but should
    # still show up by name in the grid (scored 0, not silently vanish).
    assert "Filler" in grid_html


def test_league_rosters_page_flags_players_missing_from_projections():
    _log_picks(rounds_to_log=1)

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    captions = [c.value for c in at.caption]
    assert any("No projection found for" in c and "Filler" in c for c in captions)


def test_league_rosters_page_shows_my_team_marker():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    config = _load_config()
    my_team = config["league"]["team_name"]
    grid_html = _grid_html(at)
    assert f"🎯 {my_team}" in grid_html


def test_league_rosters_page_no_longer_has_a_separate_summary_dataframe():
    """The first revision of this page had a separate league-wide summary
    st.dataframe above per-team expanders; the league manager asked for
    one unified grid instead (2026-08-28, 2nd revision) -- confirm that
    table's gone and everything lives in the single HTML grid."""
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    assert len(at.dataframe) == 0
