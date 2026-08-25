import pandas as pd
import pytest

from src.draft_tendencies import (
    available_years,
    counts_by_round,
    cumulative_counts_by_pick,
    next_run_positions,
    predict_position_counts,
    teams_per_round,
)


def _synthetic_history() -> pd.DataFrame:
    """Two tiny 2-team, 3-round seasons with a deliberate, predictable
    pattern: round 1 is always QB/QB, round 2 is always RB/RB, round 3
    is always WR/WR. Also includes one skipped pick and one no-position
    pick that must be excluded from all counts."""
    rows = []
    for year in (2024, 2025):
        picks = [
            (1, 1, "QB"), (1, 2, "QB"),
            (2, 1, "RB"), (2, 2, "RB"),
            (3, 1, "WR"), (3, 2, "WR"),
        ]
        for i, (rnd, pick_in_round, pos) in enumerate(picks):
            overall = (rnd - 1) * 2 + pick_in_round
            rows.append(dict(
                year=year, round=rnd, pick_in_round=pick_in_round,
                overall_pick=overall, team=f"Team{pick_in_round}",
                player_name=f"Player{overall}", position=pos,
                positions=pos, nfl_team="XXX", is_auto_pick=False, is_skipped=False,
            ))
    # add a skipped pick and a no-position row that should never be counted
    rows.append(dict(
        year=2024, round=1, pick_in_round=1, overall_pick=1, team="Team1",
        player_name=None, position=None, positions="", nfl_team=None,
        is_auto_pick=False, is_skipped=True,
    ))
    return pd.DataFrame(rows)


def test_teams_per_round_and_available_years():
    df = _synthetic_history()
    assert teams_per_round(df) == 2
    assert available_years(df) == [2024, 2025]


def test_counts_by_round_matches_the_deliberate_pattern():
    df = _synthetic_history()
    out = counts_by_round(df)
    assert out.loc[1, "QB"] == pytest.approx(2.0)
    assert out.loc[1, "RB"] == pytest.approx(0.0)
    assert out.loc[2, "RB"] == pytest.approx(2.0)
    assert out.loc[3, "WR"] == pytest.approx(2.0)


def test_counts_by_round_can_filter_to_a_single_year():
    df = _synthetic_history()
    out = counts_by_round(df, years=[2025])
    assert out.loc[1, "QB"] == pytest.approx(2.0)


def test_cumulative_counts_by_pick_is_monotonic_and_ends_at_totals():
    df = _synthetic_history()
    cum = cumulative_counts_by_pick(df)
    # by the last pick (6), 2 of each position have been drafted every year
    assert cum.loc[6, "QB"] == pytest.approx(2.0)
    assert cum.loc[6, "RB"] == pytest.approx(2.0)
    assert cum.loc[6, "WR"] == pytest.approx(2.0)
    # QB count should already be maxed out by pick 2 (both QBs go round 1)
    assert cum.loc[2, "QB"] == pytest.approx(2.0)
    assert cum.loc[2, "RB"] == pytest.approx(0.0)
    # monotonic non-decreasing
    assert (cum["RB"].diff().dropna() >= 0).all()


def test_predict_position_counts_flags_the_upcoming_run():
    df = _synthetic_history()
    # standing at pick 3 (about to make pick 3), looking 2 picks ahead
    # (picks 3-4) should predict 2 RBs and nothing else, matching the
    # deliberate round-2-is-RB pattern.
    predicted = predict_position_counts(df, years=None, current_overall_pick=3, picks_ahead=2)
    assert predicted["RB"] == pytest.approx(2.0)
    assert predicted.get("QB", 0.0) == pytest.approx(0.0)
    assert predicted.get("WR", 0.0) == pytest.approx(0.0)


def test_next_run_positions_ranks_and_filters_negligible_positions():
    df = _synthetic_history()
    top = next_run_positions(df, years=None, current_overall_pick=3, picks_ahead=2, top_n=2)
    assert top == ["RB"]  # QB/WR are ~0 in this window, filtered by min_expected


def test_empty_dataframe_returns_empty_results_without_raising():
    empty = pd.DataFrame(columns=[
        "year", "round", "pick_in_round", "overall_pick", "team",
        "player_name", "position", "positions", "nfl_team",
        "is_auto_pick", "is_skipped",
    ])
    assert counts_by_round(empty).empty
    assert cumulative_counts_by_pick(empty).empty
    assert predict_position_counts(empty, None, 1, 10).empty
    assert next_run_positions(empty, None, 1, 10) == []
