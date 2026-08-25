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
    # A tight cluster of 3 (internal spread 10, 100->90), a big 40-pt
    # cliff, then a tight cluster of 3 (internal spread 10, 50->40). Total
    # range is 60, so a 20% spread cap (=12) comfortably fits each
    # cluster's own 10-pt spread while rejecting the 40-pt cliff, so Jenks
    # should land on exactly this clean 2-way split.
    board = _board("RB", [100, 95, 90, 50, 45, 40])
    out = compute_tiers(board, max_spread_fraction=0.20)  # cap = 12
    out = out.sort_values("score_total", ascending=False)
    assert out["tier"].tolist() == [1, 1, 1, 2, 2, 2]


def test_automatic_tiers_never_exceed_the_spread_cap():
    """The defining guarantee of the spread-cap Jenks method: no
    automatically-chosen tier should span more than max_spread_fraction of
    the position's total point range (unless max_tiers caps it first)."""
    board = _board("K", [100, 90, 80, 70, 60])  # range 40, uniform 10-pt steps
    out = compute_tiers(board, max_spread_fraction=0.08, max_tiers=15)  # cap = 3.2
    for _tier, group in out.groupby("tier"):
        spread = group["score_total"].max() - group["score_total"].min()
        assert spread <= 3.2 + 1e-9
    # a 10-pt-step ladder can't satisfy a 3.2-pt cap without every player
    # getting its own tier
    assert out["tier"].nunique() == 5


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


def test_automatic_tiers_on_real_data_are_not_absurdly_wide():
    """Regression for the league-manager's 'tiers seem too wide' feedback:
    on the real 2026 QB pool, the old gap-based automatic methods put 30
    QBs (spanning 218 points) in a single top tier, because a large,
    gradually-declining pool has no single standout gap for a gap-based
    detector to key on. The spread-cap Jenks method must keep every
    automatic tier within its configured fraction of that position's own
    point range, regardless of pool shape."""
    from src.data_sources.manual_import import load_many
    from src.projections import build_draft_board

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    df = load_many([
        (os.path.join(root, "data", "projections", "cbs_2026.csv"), "cbs"),
        (os.path.join(root, "data", "projections", "fantasypros_2026.csv"), "fantasypros"),
        (os.path.join(root, "data", "projections", "fftoday_2026.csv"), "fftoday"),
    ])
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    board = build_draft_board(df, config)
    tiered = compute_tiers(board)  # defaults: automatic, max_spread_fraction=0.08

    for pos, group in tiered.groupby("position"):
        pos_range = group["score_total"].max() - group["score_total"].min()
        cap = pos_range * 0.08
        for _tier, tier_group in group.groupby("tier"):
            spread = tier_group["score_total"].max() - tier_group["score_total"].min()
            assert spread <= cap + 1e-6, f"{pos} tier spread {spread:.1f} exceeds cap {cap:.1f}"


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
