import pandas as pd
import pytest

from src.draft_state import Pick
from src.draft_tendencies import (
    actual_cumulative_at_pick,
    available_years,
    counts_by_round,
    cumulative_counts_by_pick,
    historical_cumulative_at_pick,
    next_run_positions,
    predict_position_counts,
    round_preserve_sum,
    round_table_preserve_row_sums,
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


def _pick(overall, rnd, pick_in_round, team, position):
    return Pick(
        overall_pick=overall, round=rnd, pick_in_round=pick_in_round,
        team=team, player_name=f"Player{overall}", position=position,
    )


def test_actual_cumulative_at_pick_counts_by_position_through_the_given_pick():
    picks = [
        _pick(1, 1, 1, "Team1", "QB"),
        _pick(2, 1, 2, "Team2", "RB"),
        _pick(3, 2, 1, "Team1", "RB"),
    ]
    assert actual_cumulative_at_pick(picks, 2) == {
        "QB": 1, "RB": 1, "WR": 0, "TE": 0, "K": 0, "DST": 0,
    }
    through_3 = actual_cumulative_at_pick(picks, 3)
    assert through_3["RB"] == 2
    assert through_3["QB"] == 1


def test_actual_cumulative_at_pick_ignores_blank_or_unrecognized_positions():
    picks = [
        _pick(1, 1, 1, "Team1", ""),  # blank -- e.g. a name-only manual log entry
        _pick(2, 1, 2, "Team2", "FLEX"),  # not one of the tracked positions
        _pick(3, 2, 1, "Team1", "QB"),
    ]
    counts = actual_cumulative_at_pick(picks, 3)
    assert counts["QB"] == 1
    assert sum(counts.values()) == 1


def test_actual_cumulative_at_pick_empty_pick_list_returns_all_zeros():
    assert actual_cumulative_at_pick([], 10) == {
        "QB": 0, "RB": 0, "WR": 0, "TE": 0, "K": 0, "DST": 0,
    }


def test_actual_cumulative_at_pick_respects_a_custom_positions_tuple():
    picks = [_pick(1, 1, 1, "Team1", "QB"), _pick(2, 1, 2, "Team2", "RB")]
    assert actual_cumulative_at_pick(picks, 2, positions=("QB",)) == {"QB": 1}


def test_historical_cumulative_at_pick_matches_the_underlying_table():
    df = _synthetic_history()
    cum = cumulative_counts_by_pick(df)
    row = historical_cumulative_at_pick(cum, 2)
    assert row["QB"] == pytest.approx(cum.loc[2, "QB"])
    assert row["RB"] == pytest.approx(cum.loc[2, "RB"])


def test_historical_cumulative_at_pick_clips_above_the_max_pick():
    df = _synthetic_history()
    cum = cumulative_counts_by_pick(df)
    max_pick = cum.index.max()
    row = historical_cumulative_at_pick(cum, max_pick + 50)
    expected = cum.loc[max_pick]
    assert row["QB"] == pytest.approx(expected["QB"])
    assert row["WR"] == pytest.approx(expected["WR"])


def test_historical_cumulative_at_pick_clips_below_pick_one():
    df = _synthetic_history()
    cum = cumulative_counts_by_pick(df)
    row = historical_cumulative_at_pick(cum, 0)
    expected = cum.loc[1]
    assert row["QB"] == pytest.approx(expected["QB"])


def test_historical_cumulative_at_pick_empty_dataframe_returns_empty_series():
    assert historical_cumulative_at_pick(pd.DataFrame(), 5).empty


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


def test_round_preserve_sum_matches_naive_rounding_when_it_already_works():
    values = pd.Series({"QB": 4.0, "RB": 4.0, "WR": 2.0})
    out = round_preserve_sum(values, target=10)
    assert out.to_dict() == {"QB": 4, "RB": 4, "WR": 2}
    assert out.sum() == 10


def test_round_preserve_sum_fixes_the_case_where_naive_rounding_would_miss_the_target():
    # round(3.4)=3, round(3.4)=3, round(3.2)=3 -> naive sum is 9, not 10.
    # Largest-remainder method must still land on exactly 10, handing the
    # extra pick to the largest fractional remainder (both 3.4s tie at
    # 0.4 > 0.2, so one of the two 3.4s gets bumped to 4).
    values = pd.Series({"QB": 3.4, "RB": 3.4, "WR": 3.2})
    out = round_preserve_sum(values, target=10)
    assert out.sum() == 10
    assert out["WR"] == 3  # smallest remainder, doesn't get the extra pick
    assert set(out.tolist()) == {3, 4}


def test_round_preserve_sum_handles_the_real_reported_case():
    # The actual values reported: 4.75 QB / 4.75 RB / 0.5 WR (round 1,
    # all years averaged) must round to integers summing to 10.
    values = pd.Series({"QB": 4.75, "RB": 4.75, "WR": 0.5})
    out = round_preserve_sum(values, target=10)
    assert out.sum() == 10
    assert set(out.tolist()) <= {0, 1, 4, 5}


def test_round_preserve_sum_all_zero_values():
    values = pd.Series({"QB": 0.0, "RB": 0.0})
    out = round_preserve_sum(values, target=0)
    assert out.to_dict() == {"QB": 0, "RB": 0}


def test_round_table_preserve_row_sums_every_row_sums_to_target():
    df = _synthetic_history()
    table = counts_by_round(df)
    rounded = round_table_preserve_row_sums(table, target=2)  # 2 teams/round in the synthetic data
    assert (rounded.sum(axis=1) == 2).all()
    assert rounded.values.dtype.kind == "i"


def test_round_table_preserve_row_sums_empty_table():
    assert round_table_preserve_row_sums(pd.DataFrame(), target=10).empty


def test_real_history_rounded_by_round_table_always_sums_to_teams_per_round():
    """Integration check against the actual captured 2022-2025 data: every
    round, for every selectable subset of years, should round to exactly
    teams_per_round players after apportionment."""
    import os
    from src.data_sources.draft_history import load_draft_history

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    df = load_draft_history(os.path.join(root, "data", "draft_history", "draft_history.csv"))
    n = teams_per_round(df)

    for years in (None, [2025], [2024, 2025], [2022, 2023, 2024, 2025]):
        table = counts_by_round(df, years=years)
        rounded = round_table_preserve_row_sums(table, target=n)
        assert (rounded.sum(axis=1) == n).all(), f"years={years} broke row-sum={n}"
