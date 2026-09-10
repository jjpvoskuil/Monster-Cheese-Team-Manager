"""
Regression test for the cache-key bug found 2026-09-10: every page's
per-page injury-lookup cache function (`_injury_lookup`/
`get_injury_lookup` in pages/1_Draft_Board.py, 4_My_Roster.py,
6_League_Rosters.py, 8_Weekly_Matchup.py, 9_Waiver_Wire.py,
10_Trade_Finder.py) is wrapped in `@st.cache_data` and takes the
injury CSV's mtime as its only argument. Streamlit's cache_data
silently excludes leading-underscore parameters from the cache key --
these functions were all originally written as `_injury_lookup(_mtime)`,
which meant the function only ever ran ONCE per Streamlit process no
matter how many times data/injury_report/current.csv actually changed
underneath it. A league manager caught this as "Meyers shows up on the
Weekly Matchup page but not the others" -- whichever pages he'd already
opened before a fresh capture landed stayed frozen on their first
(possibly empty) cached result.

These tests reuse the SAME AppTest instance across two `.run()` calls
(rather than building a fresh AppTest per assertion, which would hide
this bug class entirely -- a brand-new Python process has an empty
cache regardless of the parameter name) to reproduce the actual
long-running-server scenario: render once against injury data that
doesn't flag a given player, change the underlying CSV, rerun the same
session, and confirm the page picks up the change. Two representative
pages are covered here (one of each cache-function name/shape); all six
pages share the identical fix, called out at each site.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.draft_state import DraftState

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")
TRANSACTIONS_CSV = os.path.join(ROOT, "data", "transactions", "transactions.csv")
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
INJURY_CSV = os.path.join(ROOT, "data", "injury_report", "current.csv")

INJURY_COLUMNS = ["name", "nfl_team", "designation", "headline", "note", "effective_time", "source_file"]


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


@pytest.fixture(autouse=True)
def _clean_transactions_csv():
    backup = None
    if os.path.exists(TRANSACTIONS_CSV):
        with open(TRANSACTIONS_CSV) as f:
            backup = f.read()
        os.remove(TRANSACTIONS_CSV)
    yield
    if os.path.exists(TRANSACTIONS_CSV):
        os.remove(TRANSACTIONS_CSV)
    if backup is not None:
        os.makedirs(os.path.dirname(TRANSACTIONS_CSV), exist_ok=True)
        with open(TRANSACTIONS_CSV, "w") as f:
            f.write(backup)


@pytest.fixture(autouse=True)
def _save_restore_injury_csv():
    """The real committed current.csv is swapped out mid-test to prove
    a rerun picks up a changed file -- always put it back afterward."""
    backup = None
    if os.path.exists(INJURY_CSV):
        with open(INJURY_CSV) as f:
            backup = f.read()
    yield
    if backup is not None:
        with open(INJURY_CSV, "w") as f:
            f.write(backup)
    elif os.path.exists(INJURY_CSV):
        os.remove(INJURY_CSV)


def _write_injury_csv(rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(INJURY_CSV), exist_ok=True)
    pd.DataFrame(rows, columns=INJURY_COLUMNS).to_csv(INJURY_CSV, index=False)


def test_my_roster_page_picks_up_a_new_flag_on_rerun_same_session():
    # Log a single, distinctively-named pick for my team.
    with open(CONFIG_PATH) as f:
        import yaml
        config = yaml.safe_load(f)
    teams = config["draft"]["team_order"]
    my_team = config["league"]["team_name"]
    ds = DraftState(
        teams=teams, rounds=config["draft"]["rounds"], my_team=my_team,
        state_file=DRAFT_STATE_FILE,
        reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
    )
    while ds.on_the_clock != my_team:
        ds.log_pick_on_the_clock("Filler", position="RB")
    ds.log_pick_on_the_clock("Cache Test Player", position="WR")

    # No injury data at all yet -- page should render the player unflagged.
    _write_injury_csv([])
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/4_My_Roster.py")
    at.run(timeout=60)
    assert not at.exception
    bench_df = next(d.value for d in at.dataframe if "Cache Test Player" in d.value.get("Player", []).values)
    assert bench_df.loc[bench_df["Player"] == "Cache Test Player", "Inj"].iloc[0] == ""

    # Now a fresh capture flags that same player -- rerun the SAME
    # session (this is the part that catches the underscore-cache bug;
    # a new AppTest here would pass even with the bug still present).
    _write_injury_csv([{
        "name": "Cache Test Player", "nfl_team": "XXX", "designation": "Questionable",
        "headline": "Test headline", "note": "Test note.",
        "effective_time": "2026-09-10 12:00:00", "source_file": "test.txt",
    }])
    at.run(timeout=60)
    assert not at.exception
    bench_df = next(d.value for d in at.dataframe if "Cache Test Player" in d.value.get("Player", []).values)
    assert bench_df.loc[bench_df["Player"] == "Cache Test Player", "Inj"].iloc[0] == "❓ Quest."


def test_draft_board_page_picks_up_a_new_flag_on_rerun_same_session():
    # Empty draft -- Josh Allen (real data/projections/cbs_2026.csv
    # entry) stays in the available/undrafted board throughout.
    _write_injury_csv([])
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/1_Draft_Board.py")
    at.run(timeout=60)
    assert not at.exception

    def _board_row():
        df = next(
            d.value for d in at.dataframe
            if "Player" in d.value.columns and (d.value["Player"] == "Josh Allen").any()
        )
        return df.loc[df["Player"] == "Josh Allen"].iloc[0]

    assert _board_row()["Inj"] == ""

    _write_injury_csv([{
        "name": "Josh Allen", "nfl_team": "BUF", "designation": "Limited",
        "headline": "Test headline", "note": "Test note.",
        "effective_time": "2026-09-10 12:00:00", "source_file": "test.txt",
    }])
    at.run(timeout=60)
    assert not at.exception
    assert _board_row()["Inj"] == "⚠️ Limited"
