"""
Unit tests for src/scoring.py against the real bucket tables in
config/league_settings.yaml (captured 2026-08-24 from the live CBS rules
page). These pin down the tier boundaries so a future config edit that
changes a value is caught immediately.
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scoring import ScoringEngine, load_config, _tier_lookup  # noqa: E402

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config",
                            "league_settings.yaml")


@pytest.fixture(scope="module")
def config():
    return load_config(CONFIG_PATH)


@pytest.fixture(scope="module")
def engine(config):
    return ScoringEngine(config)


# ---------------------------------------------------------------------
# Tier lookup primitives
# ---------------------------------------------------------------------

def test_tier_lookup_exact_tier():
    tiers = [[100, 124, 9], [125, 149, 11]]
    assert _tier_lookup(110, tiers) == 9
    assert _tier_lookup(124, tiers) == 9
    assert _tier_lookup(125, tiers) == 11


def test_tier_lookup_below_lowest_is_zero():
    tiers = [[20, 29, 2], [30, 49, 3]]
    assert _tier_lookup(5, tiers) == 0
    assert _tier_lookup(0, tiers) == 0


def test_tier_lookup_gap_between_tiers_is_zero():
    # The real defensive PA table has a genuine gap: 0-0=15, then jumps to 2-6=5.
    # PA of exactly 1 falls in that gap and scores 0, per the literal league rule.
    tiers = [[0, 0, 15], [2, 6, 5], [7, 13, 2]]
    assert _tier_lookup(1, tiers) == 0


def test_tier_lookup_extrapolates_beyond_top_tier():
    # Passing yardage table tops out at 600-624 = 38. Slope from the prior
    # tier (575-599=36) is +2 per 25-yard bracket.
    tiers = [[575, 599, 36], [600, 624, 38]]
    assert _tier_lookup(650, tiers) == 42  # 2 brackets beyond 624 -> +4


# ---------------------------------------------------------------------
# Real bucket-table values, taken directly from the CBS rules page
# ---------------------------------------------------------------------

def test_passing_yardage_tiers_match_cbs(engine):
    assert engine.score_passing_game(yards=300) == pytest.approx(14)
    assert engine.score_passing_game(yards=174) == pytest.approx(2)
    assert engine.score_passing_game(yards=624) == pytest.approx(38)


def test_rushing_yardage_tiers_match_cbs(engine):
    assert engine.score_rushing_game(yards=110) == pytest.approx(9)
    assert engine.score_rushing_game(yards=74) == pytest.approx(5)


def test_receiving_yardage_and_reception_tiers_match_cbs(engine):
    assert engine.score_receiving_game(yards=100) == pytest.approx(8)
    assert engine.score_receiving_game(receptions=9) == pytest.approx(4)


def test_defense_points_allowed_shutout_bonus(engine):
    pts = engine.score_defense_game(points_allowed=0)
    assert pts == pytest.approx(15)


def test_defense_yards_allowed_stingy_bonus(engine):
    pts = engine.score_defense_game(yards_allowed=90)
    assert pts == pytest.approx(10)


def test_td_base_and_long_bonus(engine):
    # Rushing TD: base 6, +2 if 11-100 yds
    assert engine.score_rushing_game(yards=0, td=1) == pytest.approx(6)
    # Receiving TD: base 7
    assert engine.score_receiving_game(td=1) == pytest.approx(7)


def test_fg_base_and_missed_xp(engine):
    assert engine.score_kicking_game(fg_made=1) == pytest.approx(3)
    assert engine.score_kicking_game(xp_missed=1) == pytest.approx(-1)


def test_interception_and_fumble_penalties(engine):
    assert engine.score_passing_game(interceptions=1) == pytest.approx(-3)
    assert engine.score_fumbles(fumbles_lost=1) == pytest.approx(-1)


# ---------------------------------------------------------------------
# Season-total approximation
# ---------------------------------------------------------------------

def test_season_scoring_qb_reasonable(engine):
    # A strong statistical QB season: ~4200 pass yds, 30 pass TD, 10 INT over 17 games
    row = {
        "pass_yards": 4200, "pass_td": 30, "pass_int": 10, "games": 17,
        "rush_yards": 200, "rush_td": 2,
    }
    bd = engine.score_player_season(row, games=17)
    assert bd.total > 200  # sanity: a good QB season should clear 200 pts in this scoring system
    assert bd.passing > 0
    assert bd.rushing > 0


def test_season_scoring_dst_uses_per_game_allowed(engine):
    row = {
        "def_sacks": 45, "def_int": 15, "def_fumble_rec": 10, "def_td": 3,
        "points_allowed_per_game": 18, "yards_allowed_per_game": 320, "games": 17,
    }
    bd = engine.score_player_season(row, games=17)
    assert bd.defense > 0


def test_replacement_level_players_score_near_zero(engine):
    row = {"games": 17}
    bd = engine.score_player_season(row, games=17)
    assert bd.total == 0
