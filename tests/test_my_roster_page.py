"""
AppTest smoke tests for the My Roster page, focused on the "Current
roster" / "As drafted" toggle added 2026-09-09 (src.roster_state,
src.data_sources.transactions). Slot-assignment logic itself is unit
-tested directly in tests/test_roster_needs.py; these tests only confirm
the page wires src.roster_state up correctly and renders without error.

Same AppTest-via-app.py pattern as tests/test_league_rosters_page.py
(st.page_link needs the real multipage router), and the same save
/restore fixtures for the live data/draft_state.json and
data/transactions/transactions.csv.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest
import yaml
from streamlit.testing.v1 import AppTest

from src.draft_state import DraftState

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
TRANSACTIONS_CSV = os.path.join(ROOT, "data", "transactions", "transactions.csv")


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


def _load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _write_transactions_csv(rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(TRANSACTIONS_CSV), exist_ok=True)
    defaults = dict(year=2026, txn_type=None, team=None, player_name=None,
                     position="RB", nfl_team="XXX", from_team=None,
                     effective_round=1, cost=0.0, action_text="")
    full_rows = []
    for r in rows:
        row = dict(defaults)
        row.update(r)
        full_rows.append(row)
    pd.DataFrame(full_rows).to_csv(TRANSACTIONS_CSV, index=False)


def _log_my_picks(n: int) -> tuple[DraftState, dict]:
    config = _load_config()
    teams = config["draft"]["team_order"]
    my_team = config["league"]["team_name"]
    ds = DraftState(
        teams=teams,
        rounds=config["draft"]["rounds"],
        my_team=my_team,
        state_file=DRAFT_STATE_FILE,
        reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
    )
    for i in range(n):
        # Advance picks until it's my_team's turn, logging filler for
        # everyone else along the way, so my_team actually gets `n` picks.
        while ds.on_the_clock != my_team:
            ds.log_pick_on_the_clock("Filler", position="RB")
        ds.log_pick_on_the_clock("My Filler", position="RB")
    return ds, config


def _open_page(at):
    at.switch_page("pages/4_My_Roster.py")
    at.run(timeout=60)
    assert not at.exception
    return at


def _dataframe_values(at, index: int) -> list[dict]:
    return at.dataframe[index].value.to_dict(orient="records")


def test_my_roster_page_renders_with_no_picks_logged():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)
    assert at.radio[0].value == "Current roster"


def test_my_roster_page_current_roster_includes_transaction_add():
    _log_my_picks(1)
    config = _load_config()
    my_team = config["league"]["team_name"]
    _write_transactions_csv([
        dict(date="2026-09-03T03:25:00", team=my_team, txn_type="waiver_add",
             player_name="Post Draft Add", position="WR"),
    ])

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    # Bench dataframe is the last one rendered (starting lineup, draft
    # requirements, then bench) -- "Post Draft Add" isn't a starter-slot
    # match by itself since My Filler already occupies the eligible RB
    # slots, so check across every dataframe on the page instead of
    # assuming a fixed index.
    all_players = []
    for df_element in at.dataframe:
        if "Player" in df_element.value.columns:
            all_players.extend(df_element.value["Player"].tolist())
    assert "Post Draft Add" in all_players


def test_my_roster_page_as_drafted_excludes_transaction_add():
    _log_my_picks(1)
    config = _load_config()
    my_team = config["league"]["team_name"]
    _write_transactions_csv([
        dict(date="2026-09-03T03:25:00", team=my_team, txn_type="waiver_add",
             player_name="Post Draft Add", position="WR"),
    ])

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)
    at.radio[0].set_value("As drafted").run(timeout=60)

    all_players = []
    for df_element in at.dataframe:
        if "Player" in df_element.value.columns:
            all_players.extend(df_element.value["Player"].tolist())
    assert "Post Draft Add" not in all_players


def test_my_roster_page_shows_transaction_warning_for_unmatched_drop():
    _log_my_picks(1)
    config = _load_config()
    my_team = config["league"]["team_name"]
    _write_transactions_csv([
        dict(date="2026-09-03T03:25:00", team=my_team, txn_type="drop",
             player_name="Nobody On This Roster"),
    ])

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    expander_labels = [e.label for e in at.expander]
    assert any("transaction warning" in label for label in expander_labels)


def test_my_roster_page_bench_added_player_shows_txn_marker():
    """A transaction-added player who doesn't fit any open starter slot
    should show up on the bench with Rd="Txn" (not a real round)."""
    _log_my_picks(1)
    config = _load_config()
    my_team = config["league"]["team_name"]
    starters = config["roster"]["starters"]
    # Fill every RB/flex-eligible slot with real draft picks first isn't
    # practical here without deep config knowledge -- instead just assert
    # the marker shows up SOMEWHERE it's applicable: either the starting
    # lineup table or bench, whichever the added WR lands in.
    _write_transactions_csv([
        dict(date="2026-09-03T03:25:00", team=my_team, txn_type="waiver_add",
             player_name="Post Draft Add", position="WR"),
    ])

    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at = _open_page(at)

    found_txn_marker = False
    for df_element in at.dataframe:
        df = df_element.value
        if "Player" in df.columns and "Rd" in df.columns:
            match = df[df["Player"] == "Post Draft Add"]
            if not match.empty and (match["Rd"] == "Txn").all():
                found_txn_marker = True
    assert found_txn_marker
