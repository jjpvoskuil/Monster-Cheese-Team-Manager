import os
import tempfile

import pandas as pd
import pytest

from src.draft_state import DraftState, Pick
from src.pick_suggestion import (
    PositionScore,
    my_position_need,
    picks_before_my_next_turn,
    suggest_position,
    top_available_players,
)

TEAMS = [f"Team {i}" for i in range(1, 11)]
TEAMS[3] = "Monster Cheese"

STARTERS = [
    {"slot": "QB", "count": 1, "eligible": ["QB"]},
    {"slot": "RB", "count": 2, "eligible": ["RB"]},
    {"slot": "WR_TE_FLEX", "count": 2, "eligible": ["WR", "TE"]},
    {"slot": "TE", "count": 1, "eligible": ["TE"]},
    {"slot": "K", "count": 1, "eligible": ["K"]},
    {"slot": "SUPERFLEX", "count": 1, "eligible": ["QB", "RB", "WR", "TE"]},
    {"slot": "FLEX", "count": 1, "eligible": ["RB", "WR", "TE", "K"]},
    {"slot": "DST", "count": 1, "eligible": ["DST"]},
]
CONFIG = {"roster": {"starters": STARTERS}}


def _fresh_state(rounds=15):
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    return DraftState(teams=TEAMS, rounds=rounds, my_team="Monster Cheese", state_file=tmp.name)


def _player(name, position, vor, vor_rank, tier, nfl_team="XXX", score_total=None):
    return {
        "name": name,
        "position": position,
        "nfl_team": nfl_team,
        "vor": vor,
        "vor_rank": vor_rank,
        "tier": tier,
        "score_total": score_total if score_total is not None else vor + 100,
    }


def _board(rows):
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------
# picks_before_my_next_turn
# ---------------------------------------------------------------------

def test_picks_before_my_next_turn_when_it_is_my_pick_looks_past_current_pick():
    ds = _fresh_state()
    # Monster Cheese is slot index 3 (0-indexed) -> pick 4 in round 1.
    for _ in range(3):
        ds.log_pick_on_the_clock("Filler", position="RB")
    assert ds.is_my_pick
    # Snake: after pick 4 (mine), picks 5-10 go to others (6 picks), then
    # round 2 snakes back so pick 11 = Team 10, ... pick 17 = Monster
    # Cheese again (index 3 from the end: 20-3=17). That's 12 picks
    # between my current pick and my next one.
    assert picks_before_my_next_turn(ds) == 12


def test_picks_before_my_next_turn_when_not_my_pick_matches_picks_until_my_turn():
    ds = _fresh_state()
    ds.log_pick_on_the_clock("Filler", position="RB")  # pick 1, not mine
    assert not ds.is_my_pick
    assert picks_before_my_next_turn(ds) == ds.picks_until_my_turn()


def test_picks_before_my_next_turn_is_zero_when_draft_complete():
    ds = _fresh_state(rounds=1)
    for _ in range(10):
        ds.log_pick_on_the_clock("Filler", position="RB")
    assert ds.is_draft_complete
    assert picks_before_my_next_turn(ds) == 0


# ---------------------------------------------------------------------
# my_position_need
# ---------------------------------------------------------------------

def test_my_position_need_empty_roster_wants_every_dedicated_slot():
    ds = _fresh_state()
    need = my_position_need(ds, CONFIG)
    assert need["QB"] > 0
    assert need["RB"] > 0
    assert need["DST"] > 0


def test_my_position_need_drops_once_slots_are_filled():
    ds = _fresh_state()
    # Fill QB, RB x2, DST via manual log_pick calls for my own team.
    ds.log_pick("Monster Cheese", "QB1", position="QB")
    ds.log_pick("Monster Cheese", "RB1", position="RB")
    ds.log_pick("Monster Cheese", "RB2", position="RB")
    ds.log_pick("Monster Cheese", "DST1", position="DST")
    need = my_position_need(ds, CONFIG)
    # QB's only dedicated slot is filled; SUPERFLEX (QB-eligible) is still
    # open though, so QB need should be smaller than before but not
    # necessarily exactly zero.
    ds2 = _fresh_state()
    need_empty = my_position_need(ds2, CONFIG)
    assert need.get("QB", 0) < need_empty["QB"]
    assert need.get("RB", 0) < need_empty["RB"]
    assert "DST" not in need or need["DST"] == 0


# ---------------------------------------------------------------------
# suggest_position
# ---------------------------------------------------------------------

def test_suggest_position_prefers_clear_need_and_value_winner():
    ds = _fresh_state()
    # My roster is empty -- every dedicated slot open. Give RB a much
    # higher available VOR than everything else so it should win on both
    # value and need with no scarcity signal at all (history=None).
    board = _board([
        _player("Elite RB", "RB", vor=50.0, vor_rank=1, tier=1),
        _player("Good WR", "WR", vor=20.0, vor_rank=5, tier=1),
        _player("Good QB", "QB", vor=15.0, vor_rank=8, tier=1),
        _player("Good TE", "TE", vor=10.0, vor_rank=12, tier=1),
        _player("Good K", "K", vor=1.0, vor_rank=50, tier=1),
        _player("Good DST", "DST", vor=1.0, vor_rank=51, tier=1),
    ])
    suggestion = suggest_position(board, ds, CONFIG, history=None)
    assert suggestion.recommended_position == "RB"
    assert "Recommended: RB" in suggestion.reasoning
    assert len(suggestion.all_scores) == 6


def test_suggest_position_scarcity_can_flip_the_recommendation():
    ds = _fresh_state()
    # RB and WR have identical value/need, but RB has only 1 tier-1
    # player left and history predicts a big RB run before my next turn,
    # while WR has plenty of tier-1 depth and no predicted run. Scarcity
    # should push RB ahead even though value/need alone are a tie.
    board = _board([
        _player("RB1", "RB", vor=30.0, vor_rank=2, tier=1),
        _player("WR1", "WR", vor=30.0, vor_rank=3, tier=1),
        _player("WR2", "WR", vor=29.0, vor_rank=4, tier=1),
        _player("WR3", "WR", vor=28.0, vor_rank=5, tier=1),
    ])
    history = pd.DataFrame([
        {"year": 2025, "round": r, "pick_in_round": s, "overall_pick": (r - 1) * 10 + s,
         "position": "RB", "is_skipped": False}
        for r in (1, 2) for s in range(1, 11)
    ])
    # Force a large predicted RB count in the horizon window by having
    # every historical pick be RB (an extreme but deterministic fixture).
    suggestion = suggest_position(board, ds, CONFIG, history=history, years=[2025])
    rb_score = next(s for s in suggestion.all_scores if s.position == "RB")
    wr_score = next(s for s in suggestion.all_scores if s.position == "WR")
    assert rb_score.scarcity_ratio > wr_score.scarcity_ratio
    assert suggestion.recommended_position == "RB"


def test_suggest_position_handles_missing_history_gracefully():
    ds = _fresh_state()
    board = _board([_player("QB1", "QB", vor=10.0, vor_rank=1, tier=1)])
    suggestion = suggest_position(board, ds, CONFIG, history=pd.DataFrame())
    assert suggestion.recommended_position == "QB"
    for s in suggestion.all_scores:
        assert s.predicted_picks == 0.0
        assert s.scarcity_ratio == 0.0


def test_suggest_position_returns_none_when_draft_complete():
    ds = _fresh_state(rounds=1)
    for _ in range(10):
        ds.log_pick_on_the_clock("Filler", position="RB")
    board = _board([_player("QB1", "QB", vor=10.0, vor_rank=1, tier=1)])
    suggestion = suggest_position(board, ds, CONFIG)
    assert suggestion.recommended_position is None
    assert "complete" in suggestion.reasoning.lower()


def test_suggest_position_returns_none_when_no_players_available():
    ds = _fresh_state()
    suggestion = suggest_position(pd.DataFrame(), ds, CONFIG)
    assert suggestion.recommended_position is None


# ---------------------------------------------------------------------
# top_available_players
# ---------------------------------------------------------------------

def test_top_available_players_sorted_best_vor_first():
    board = _board([
        _player("RB Low", "RB", vor=5.0, vor_rank=20, tier=2),
        _player("RB High", "RB", vor=25.0, vor_rank=3, tier=1),
        _player("RB Mid", "RB", vor=15.0, vor_rank=10, tier=1),
        _player("WR1", "WR", vor=100.0, vor_rank=1, tier=1),
    ])
    top = top_available_players(board, "RB", n=3)
    assert list(top["name"]) == ["RB High", "RB Mid", "RB Low"]


def test_top_available_players_respects_n():
    board = _board([_player(f"RB{i}", "RB", vor=float(i), vor_rank=i, tier=1) for i in range(10)])
    top = top_available_players(board, "RB", n=3)
    assert len(top) == 3


def test_top_available_players_empty_for_exhausted_position():
    board = _board([_player("QB1", "QB", vor=10.0, vor_rank=1, tier=1)])
    top = top_available_players(board, "DST", n=3)
    assert top.empty


def test_top_available_players_empty_input_board():
    top = top_available_players(pd.DataFrame(), "RB", n=3)
    assert top.empty
