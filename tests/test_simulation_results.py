"""
Unit tests for src/data_sources/simulation_results.py -- the loaders for
scripts/simulate_draft.py's --adp-csv/--team-points-csv output (punch
-list item #1). Both follow the same "optional file, empty frame if
missing" contract as src/data_sources/draft_history.py's
load_draft_history(), so the main thing worth testing here is that
contract plus a real round-trip through pandas.
"""

from __future__ import annotations

import os

import pandas as pd

from src.data_sources.simulation_results import load_adp, load_team_points


def test_load_adp_missing_file_returns_empty_frame():
    df = load_adp("/tmp/definitely_does_not_exist_adp.csv")
    assert df.empty


def test_load_team_points_missing_file_returns_empty_frame():
    df = load_team_points("/tmp/definitely_does_not_exist_team_points.csv")
    assert df.empty


def test_load_adp_reads_written_csv(tmp_path):
    path = str(tmp_path / "adp.csv")
    pd.DataFrame([
        {"name": "Player A", "position": "QB", "nfl_team": "AAA", "adp": 2.0,
         "times_drafted": 2, "trials": 2, "drafted_pct": 100.0},
    ]).to_csv(path, index=False)
    df = load_adp(path)
    assert list(df["name"]) == ["Player A"]
    assert df["adp"].iloc[0] == 2.0


def test_load_team_points_reads_written_csv(tmp_path):
    path = str(tmp_path / "team_points.csv")
    pd.DataFrame([
        {"team": "Team Y", "avg_points": 190.0, "avg_finish_rank": 1.0,
         "best_rank": 1, "worst_rank": 1, "trials": 2, "rank": 1},
    ]).to_csv(path, index=False)
    df = load_team_points(path)
    assert list(df["team"]) == ["Team Y"]
    assert df["rank"].iloc[0] == 1
