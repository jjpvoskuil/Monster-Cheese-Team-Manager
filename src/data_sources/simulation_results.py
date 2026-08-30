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


def format_adp_as_round_pick(adp: float, teams_per_round: int) -> str:
    """Punch-list item #9: display a raw overall-pick ADP (e.g. 43.2,
    meaning "on average this player goes 43rd overall") as "round.pick"
    instead -- e.g. "5.3" for "5th round, 3rd pick in that round", the
    league manager's own example (a player picked 3rd in round 5 is
    overall pick 43 in a 10-team league, so adp=43.2 -> "5.3").

    NaN (a player never drafted in any simulated trial -- see load_adp's
    docstring) and a non-positive `teams_per_round` both return an em
    dash rather than raising or printing "nan.nan", since this is a
    display-only helper and the underlying missing-ness is intentional,
    not an error.

    The pick-within-round part is rounded (not truncated) to the nearest
    whole pick and clamped to [1, teams_per_round] -- an ADP that rounds
    up past a round's last pick (e.g. 10.6 in a 10-team league) is
    clamped to that round's final pick (10) rather than spilling into
    "11", which isn't a valid pick-in-round number.
    """
    if pd.isna(adp) or teams_per_round <= 0:
        return "—"
    overall = float(adp)
    rnd = int((overall - 1) // teams_per_round) + 1
    pick_in_round = round(overall - (rnd - 1) * teams_per_round)
    pick_in_round = max(1, min(teams_per_round, pick_in_round))
    return f"{rnd}.{pick_in_round}"
