import os
import tempfile

import pytest
import yaml

from src.draft_state import DraftState
from src.roster_needs import (
    aggregate_opponent_demand,
    opponent_needs_before_next_pick,
    positions_that_would_fill,
    team_position_counts,
    unfilled_starter_slots,
)

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "league_settings.yaml",
)

TEAMS = [f"Team {i}" for i in range(1, 11)]
TEAMS[3] = "Monster Cheese"


def _fresh_state():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    return DraftState(teams=TEAMS, rounds=22, my_team="Monster Cheese", state_file=tmp.name)


def _real_starters():
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    return config, config["roster"]["starters"]


def test_team_position_counts_ignores_blank_positions():
    class FakePick:
        def __init__(self, position):
            self.position = position

    counts = team_position_counts([FakePick("QB"), FakePick("QB"), FakePick("RB"), FakePick("")])
    assert counts == {"QB": 2, "RB": 1}


def test_unfilled_starter_slots_fills_dedicated_slots_first():
    _, starters = _real_starters()
    # Drafted exactly enough for QB/RB/TE/K/DST dedicated slots, nothing
    # left over for the flex slots.
    counts = {"QB": 1, "RB": 3, "TE": 1, "K": 1, "DST": 1}
    unfilled = unfilled_starter_slots(counts, starters)
    # WR_TE_FLEX (needs 3, eligible WR/TE), SUPERFLEX (1, QB/RB/WR/TE),
    # FLEX (1, RB/WR/TE/K) should all still be fully unfilled -- nothing
    # left after the dedicated slots ate every drafted player.
    assert unfilled["WR_TE_FLEX"] == 3
    assert unfilled["SUPERFLEX"] == 1
    assert unfilled["FLEX"] == 1
    assert "QB" not in unfilled
    assert "RB" not in unfilled


def test_unfilled_starter_slots_extra_players_fill_flex_slots():
    _, starters = _real_starters()
    # A full legal-ish roster: dedicated slots plus enough extra
    # RB/WR/TE/QB/K to cover WR_TE_FLEX(3)/SUPERFLEX(1)/FLEX(1).
    counts = {"QB": 2, "RB": 4, "WR": 4, "TE": 2, "K": 1, "DST": 1}
    unfilled = unfilled_starter_slots(counts, starters)
    assert unfilled == {}


def test_positions_that_would_fill_spreads_demand_across_eligible_positions():
    _, starters = _real_starters()
    demand = positions_that_would_fill({"WR_TE_FLEX": 2}, starters)
    assert demand["WR"] == pytest.approx(1.0)
    assert demand["TE"] == pytest.approx(1.0)


def test_opponent_needs_before_next_pick_covers_only_teams_ahead_of_me():
    config, starters = _real_starters()
    ds = _fresh_state()
    # Monster Cheese is picking 4th (TEAMS[3]); log 3 picks so it becomes
    # Monster Cheese's turn (picks_until_my_turn() == 0 -> no needs owed).
    for team in TEAMS[:3]:
        ds.log_pick(team, f"{team} Player", position="RB", nfl_team="XXX")
    assert ds.is_my_pick
    assert opponent_needs_before_next_pick(ds, config) == {}


def test_opponent_needs_before_next_pick_flags_teams_with_no_picks_yet():
    config, starters = _real_starters()
    ds = _fresh_state()
    # Nobody has picked yet; Monster Cheese is 4th, so 3 teams pick first,
    # each with a totally empty roster -> every slot unfilled -> QB/RB/WR
    # should show up with real demand for all 3 upcoming teams.
    needs = opponent_needs_before_next_pick(ds, config)
    assert set(needs.keys()) == set(TEAMS[:3])
    for team, demand in needs.items():
        assert demand["QB"] > 0
        assert demand["RB"] > 0

    total = aggregate_opponent_demand(needs)
    assert total["RB"] > 0
    assert total["QB"] > 0
