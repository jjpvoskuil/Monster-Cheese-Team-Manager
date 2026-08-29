"""
Load the aggregate outputs of scripts/simulate_draft.py's Monte Carlo
draft simulations (punch-list item #1): per-player average draft
position (ADP) and per-team average simulated optimal-lineup points +
rank, both written to data/simulations/*.csv by that script's
--adp-csv/--team-points-csv flags.

Same "optional side-data CSV, not an error if missing" pattern as
src/data_sources/draft_history.py's load_draft_history() -- these files
are a precomputed convenience, not something the app depends on to
function. If they're absent (e.g. a fresh checkout before anyone has run
the simulation), callers get an empty DataFrame back and the Draft Board
just doesn't show an ADP column / simulated-strength table yet.
"""

from __future__ import annotations

import os

import pandas as pd


def load_adp(csv_path: str) -> pd.DataFrame:
    """Load the per-player ADP CSV (aggregate_adp() in
    scripts/simulate_draft.py). Columns: name, position, nfl_team, adp,
    times_drafted, trials, drafted_pct. `adp` is NaN for a player never
    drafted in any trial -- an honest missing value, not a penalty."""
    if not os.path.exists(csv_path):
        return pd.DataFrame()
    return pd.read_csv(csv_path)


def load_team_points(csv_path: str) -> pd.DataFrame:
    """Load the per-team average-simulated-points/rank CSV
    (aggregate_team_points() in scripts/simulate_draft.py). Columns:
    team, avg_points, avg_finish_rank, best_rank, worst_rank, trials,
    rank (1 = highest avg_points)."""
    if not os.path.exists(csv_path):
        return pd.DataFrame()
    return pd.read_csv(csv_path)
