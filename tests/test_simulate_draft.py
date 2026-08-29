"""
Unit tests for scripts/simulate_draft.py's aggregation functions (punch
-list item #1: ADP and per-team average simulated points/rank). These
use small synthetic TrialResult fixtures rather than actually running
simulate_one_draft() -- a real trial takes several seconds and needs the
full real 2026 projections board, which would make this suite slow and
brittle to data changes for no benefit; the aggregation MATH is what's
under test here, not the simulation itself.

scripts/ isn't a package (no __init__.py, consistent with it being a
collection of standalone CLI entrypoints, not library code) -- add it to
sys.path directly, the same way simulate_draft.py itself sys.path
-inserts its own ROOT.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import pandas as pd  # noqa: E402

from simulate_draft import TrialResult, aggregate_adp, aggregate_team_points  # noqa: E402

BOARD = pd.DataFrame([
    {"name": "Player A", "position": "QB", "nfl_team": "AAA"},
    {"name": "Player B", "position": "RB", "nfl_team": "BBB"},
    {"name": "Player C", "position": "WR", "nfl_team": "CCC"},  # never drafted in any trial below
])


def _trial(seed, picks: dict, all_points: dict) -> TrialResult:
    return TrialResult(seed=seed, my_rank=1, my_points=0.0, all_points=all_points, player_picks=picks)


def test_aggregate_adp_averages_pick_number_across_trials_where_drafted():
    results = [
        _trial(1, {"Player A": 1, "Player B": 5}, {}),
        _trial(2, {"Player A": 3, "Player B": 7}, {}),
    ]
    df = aggregate_adp(BOARD, results)
    a = df[df["name"] == "Player A"].iloc[0]
    assert a["adp"] == 2.0
    assert a["times_drafted"] == 2
    assert a["drafted_pct"] == 100.0


def test_aggregate_adp_marks_never_drafted_player_as_nan_not_penalized():
    # A player who never shows up in any trial's player_picks should NOT
    # get some worst-case pick number substituted in -- that would quietly
    # corrupt any "average ADP by position" rollup done downstream. It
    # should show up as an honest missing value instead.
    results = [_trial(1, {"Player A": 1}, {}), _trial(2, {"Player A": 2}, {})]
    df = aggregate_adp(BOARD, results)
    c = df[df["name"] == "Player C"].iloc[0]
    assert pd.isna(c["adp"])
    assert c["times_drafted"] == 0
    assert c["drafted_pct"] == 0.0


def test_aggregate_adp_sorts_by_adp_with_undrafted_last():
    results = [_trial(1, {"Player A": 5, "Player B": 1}, {})]
    df = aggregate_adp(BOARD, results)
    assert list(df["name"]) == ["Player B", "Player A", "Player C"]


def test_aggregate_team_points_ranks_by_average_points_descending():
    results = [
        _trial(1, {}, {"Team X": 100.0, "Team Y": 200.0}),
        _trial(2, {}, {"Team X": 120.0, "Team Y": 180.0}),
    ]
    df = aggregate_team_points(results)
    assert list(df["team"]) == ["Team Y", "Team X"]
    assert list(df["rank"]) == [1, 2]
    y = df[df["team"] == "Team Y"].iloc[0]
    assert y["avg_points"] == 190.0


def test_aggregate_team_points_finish_rank_reflects_per_trial_standing():
    # Team X wins trial 1 outright but craters in trial 2 -- avg_finish
    # _rank should reveal that inconsistency even though the two teams'
    # avg_points end up close.
    results = [
        _trial(1, {}, {"Team X": 300.0, "Team Y": 100.0}),
        _trial(2, {}, {"Team X": 50.0, "Team Y": 100.0}),
    ]
    df = aggregate_team_points(results)
    x = df[df["team"] == "Team X"].iloc[0]
    assert x["avg_finish_rank"] == 1.5
    assert x["best_rank"] == 1
    assert x["worst_rank"] == 2


def test_aggregate_team_points_empty_results_returns_empty_frame():
    df = aggregate_team_points([])
    assert df.empty
