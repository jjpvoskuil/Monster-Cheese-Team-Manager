import pandas as pd
import pytest
import yaml
import os

from src.projections import compute_position_demand, compute_tiers

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "league_settings.yaml",
)


def _board(position: str, scores: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "name": [f"Player{i}" for i in range(len(scores))],
        "position": [position] * len(scores),
        "score_total": scores,
        "vor": [s - 10 for s in scores],  # constant offset, like a real replacement_score subtraction
    })


def test_manual_gap_threshold_creates_expected_tiers():
    board = _board("QB", [100, 95, 80, 78, 40])
    out = compute_tiers(board, gap_threshold=10.0)
    out = out.sort_values("score_total", ascending=False)
    assert out["tier"].tolist() == [1, 1, 2, 2, 3]
    # tier_gap is only set on the boundary row (the first player of a new tier)
    assert out["tier_gap"].tolist() == [0.0, 0.0, 15.0, 0.0, 38.0]


def test_manual_gap_threshold_zero_puts_every_player_in_own_tier():
    board = _board("QB", [100, 95, 94])
    out = compute_tiers(board, gap_threshold=0.0)
    out = out.sort_values("score_total", ascending=False)
    assert out["tier"].tolist() == [1, 2, 3]


def test_automatic_detection_flags_a_clear_outlier_drop():
    # A tight cluster of 3, a big cliff, then a tight cluster of 3.
    board = _board("RB", [100, 95, 90, 50, 45, 40])
    out = compute_tiers(board)  # gap_threshold=None -> automatic
    out = out.sort_values("score_total", ascending=False)
    assert out["tier"].tolist() == [1, 1, 1, 2, 2, 2]


def test_uniform_ladder_stays_one_tier_when_automatic():
    """No real 'natural break' exists when every gap is identical -- should
    not fragment into a tier per player."""
    board = _board("K", [100, 90, 80, 70, 60])
    out = compute_tiers(board)
    assert out["tier"].nunique() == 1


def test_tiers_computed_independently_per_position():
    board = pd.concat([
        _board("QB", [300, 295, 200]),
        _board("RB", [250, 100, 95]),
    ], ignore_index=True)
    out = compute_tiers(board, gap_threshold=20.0)
    qb = out[out["position"] == "QB"].sort_values("score_total", ascending=False)
    rb = out[out["position"] == "RB"].sort_values("score_total", ascending=False)
    assert qb["tier"].tolist() == [1, 1, 2]
    assert rb["tier"].tolist() == [1, 2, 2]


def test_single_or_empty_position_group_is_one_tier():
    board = _board("DST", [50.0])
    out = compute_tiers(board, gap_threshold=1.0)
    assert out["tier"].tolist() == [1]

    empty = pd.DataFrame(columns=["name", "position", "score_total"])
    out_empty = compute_tiers(empty)
    assert out_empty.empty


def test_tiering_by_score_total_matches_tiering_by_vor():
    """vor is score_total minus a constant per position, so tier boundaries
    should be identical regardless of which metric is used."""
    board = _board("WR", [300, 280, 200, 190, 100])
    by_points = compute_tiers(board, metric="score_total", gap_threshold=15.0)
    by_vor = compute_tiers(board, metric="vor", gap_threshold=15.0)
    assert by_points.sort_index()["tier"].tolist() == by_vor.sort_index()["tier"].tolist()


def test_superflex_demand_is_now_overwhelmingly_qb():
    """Regression for the 2026-08-25 league-manager feedback: this scoring
    system makes QB the superflex slot's near-automatic fill, so most teams
    start 2 QBs almost every week. QB demand should reflect that (~1.9
    QBs/team: 1 dedicated + ~0.9 of the superflex slot), not the old
    ~1.55/team split."""
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    demand = compute_position_demand(config)
    teams = config["league"]["teams"]
    assert demand["QB"] == pytest.approx(teams * 1 + teams * 0.90)
    assert demand["QB"] / teams > 1.8
