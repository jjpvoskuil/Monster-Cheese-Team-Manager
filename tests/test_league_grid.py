import pandas as pd
import pytest

from src.draft_state import Pick
from src.league_grid import build_league_grid

STARTERS = [
    {"slot": "QB", "count": 1, "eligible": ["QB"]},
    {"slot": "RB", "count": 2, "eligible": ["RB"]},
    {"slot": "FLEX", "count": 1, "eligible": ["RB", "WR", "TE"]},
]


def _pick(name, position, overall_pick, round_=1, team="Team A"):
    return Pick(
        overall_pick=overall_pick, round=round_, pick_in_round=1,
        team=team, player_name=name, position=position, nfl_team="XXX",
    )


def test_starter_labels_expand_counts_and_number_repeated_slots():
    points = pd.Series(dtype=float)
    grid = build_league_grid({}, ["Team A"], STARTERS, points)
    assert grid.starter_labels == ["QB", "RB 1", "RB 2", "FLEX"]


def test_players_fill_dedicated_slots_before_flex():
    # Two RBs drafted -- both should land in the dedicated RB slots
    # (fewest eligible positions, filled first), leaving FLEX empty and
    # nobody on the bench, matching src.roster_needs.assign_roster_slots'
    # own documented fill order.
    picks = [_pick("RB One", "RB", 1), _pick("RB Two", "RB", 2)]
    rosters = {"Team A": picks}
    points = pd.Series({"RB One": 150.0, "RB Two": 120.0})
    grid = build_league_grid(rosters, ["Team A"], STARTERS, points)

    col = grid.columns[0]
    assert col.starter_players == ["", "RB One", "RB Two", ""]
    assert col.starter_pts == [None, 150.0, 120.0, None]
    assert col.starting_pts == 270.0
    assert col.bench_players == []
    assert col.bench_pts_total == 0.0
    assert col.total_pts == 270.0


def test_overflow_at_a_position_lands_on_the_bench():
    # Three RBs drafted but only 2 dedicated RB slots + 1 FLEX (RB
    # -eligible) = 3 slots -- the FLEX slot should absorb the 3rd RB,
    # leaving nothing for the bench in this exact case. Add a 4th RB to
    # actually force an overflow onto the bench.
    picks = [
        _pick("RB One", "RB", 1), _pick("RB Two", "RB", 2),
        _pick("RB Three", "RB", 3), _pick("RB Four", "RB", 4),
    ]
    rosters = {"Team A": picks}
    points = pd.Series({"RB One": 100.0, "RB Two": 90.0, "RB Three": 80.0, "RB Four": 70.0})
    grid = build_league_grid(rosters, ["Team A"], STARTERS, points)

    col = grid.columns[0]
    assert col.starter_players == ["", "RB One", "RB Two", "RB Three"]
    assert col.bench_players == ["RB Four"]
    assert col.bench_pts == [70.0]
    assert col.starting_pts == 270.0
    assert col.bench_pts_total == 70.0
    assert col.total_pts == 340.0


def test_a_drafted_player_missing_from_projections_scores_zero_and_is_flagged():
    picks = [_pick("Mystery Guy", "QB", 1)]
    rosters = {"Team A": picks}
    points = pd.Series({"Someone Else": 200.0})  # "Mystery Guy" not present
    grid = build_league_grid(rosters, ["Team A"], STARTERS, points)

    col = grid.columns[0]
    assert col.starter_players[0] == "Mystery Guy"
    assert col.starter_pts[0] == 0.0
    assert col.missing_projection == ["Mystery Guy"]


def test_max_bench_is_the_deepest_team_and_others_pad_short():
    picks_a = [_pick("A1", "RB", 1, team="A"), _pick("A2", "RB", 2, team="A"),
               _pick("A3", "RB", 3, team="A"), _pick("A4", "RB", 4, team="A")]
    picks_b = [_pick("B1", "RB", 5, team="B")]
    rosters = {"A": picks_a, "B": picks_b}
    points = pd.Series({"A1": 1.0, "A2": 1.0, "A3": 1.0, "A4": 1.0, "B1": 1.0})
    grid = build_league_grid(rosters, ["A", "B"], STARTERS, points)

    assert grid.max_bench == 1  # team A has exactly one bench player (A4)
    col_b = next(c for c in grid.columns if c.team == "B")
    assert col_b.bench_players == []  # team B has no bench player at all


def test_a_team_with_no_picks_gets_all_empty_starter_slots():
    grid = build_league_grid({}, ["Empty Team"], STARTERS, pd.Series(dtype=float))
    col = grid.columns[0]
    assert col.starter_players == ["", "", "", ""]
    assert col.starter_pts == [None, None, None, None]
    assert col.starting_pts == 0.0
    assert col.total_pts == 0.0


def test_column_order_matches_teams_argument_order():
    grid = build_league_grid({}, ["Z Team", "A Team"], STARTERS, pd.Series(dtype=float))
    assert [c.team for c in grid.columns] == ["Z Team", "A Team"]
