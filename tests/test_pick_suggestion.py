import os
import tempfile

import pandas as pd
import pytest

from src.draft_state import DraftState, Pick
from src.pick_suggestion import (
    PositionScore,
    _describe,
    _early_round_discount,
    _mandatory_deadline_positions,
    _position_cap,
    _redundancy_penalty,
    _remaining_my_picks,
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


def test_my_position_need_uses_flex_splits_for_a_real_second_qb_need():
    # Regression test for the bug reported 2026-08-26: drafting QB in
    # round 1 (filling the one dedicated QB slot) still leaves a real
    # 2nd-QB need for SUPERFLEX, but without flex_splits that need was
    # split evenly across QB/RB/WR/TE (0.25 each) -- so tiny it could
    # never compete with RB/WR's much larger dedicated-slot needs, and
    # the Suggested Pick panel would never recommend QB again even
    # though a 2nd QB was genuinely still needed.
    config_with_splits = {
        **CONFIG,
        "estimation_assumptions": {
            "flex_position_splits": {
                "WR_TE_FLEX": {"WR": 0.75, "TE": 0.25},
                "FLEX": {"RB": 0.40, "WR": 0.40, "TE": 0.15, "K": 0.05},
                "SUPERFLEX": {"QB": 0.90, "RB": 0.04, "WR": 0.04, "TE": 0.02},
            }
        },
    }
    ds = _fresh_state()
    ds.log_pick("Monster Cheese", "QB1", position="QB")  # fills the only dedicated QB slot

    need_even_split = my_position_need(ds, CONFIG)  # no flex_splits -- old behavior
    need_weighted = my_position_need(ds, config_with_splits)

    assert need_even_split["QB"] == pytest.approx(0.25)
    assert need_weighted["QB"] == pytest.approx(0.90)
    assert need_weighted["QB"] > need_even_split["QB"]


# ---------------------------------------------------------------------
# _remaining_my_picks / _mandatory_deadline_positions
# ---------------------------------------------------------------------

def test_remaining_my_picks_counts_current_and_future_turns():
    ds = _fresh_state(rounds=2)  # 20 total picks; Monster Cheese picks at overall 4 and 17
    assert _remaining_my_picks(ds) == 2
    for _ in range(3):
        ds.log_pick_on_the_clock("Filler", position="RB")
    assert ds.is_my_pick  # pick 4
    assert _remaining_my_picks(ds) == 2  # counts THIS pick plus the round-2 one
    ds.log_pick_on_the_clock("Filler", position="RB")  # pick 4 now logged
    assert _remaining_my_picks(ds) == 1  # only pick 17 left


def test_remaining_my_picks_is_zero_when_draft_complete():
    ds = _fresh_state(rounds=1)
    for _ in range(10):
        ds.log_pick_on_the_clock("Filler", position="RB")
    assert _remaining_my_picks(ds) == 0


def test_mandatory_deadline_positions_empty_with_plenty_of_picks_left():
    ds = _fresh_state()  # 15 rounds -- nowhere near a deadline
    assert _mandatory_deadline_positions(ds, CONFIG) == set()


def test_mandatory_deadline_positions_flags_an_unfilled_dedicated_slot_on_my_last_chance():
    ds = _fresh_state(rounds=2)
    for _ in range(16):  # picks 1-16; pick 17 is Monster Cheese's LAST pick
        ds.log_pick_on_the_clock("Filler", position="RB")
    assert ds.next_overall_pick == 17
    assert _remaining_my_picks(ds) == 1
    # Zero QBs drafted, only the dedicated QB(1) slot can ever fill it,
    # and this is the last chance -- must be flagged urgent.
    assert "QB" in _mandatory_deadline_positions(ds, CONFIG)


def test_mandatory_deadline_positions_ignores_multi_eligible_only_slots():
    # A slot eligible for more than one position is deliberately never
    # covered by this override -- it's not unambiguous which position
    # "must" fill it, so forcing one would be guessing.
    starters_flex_only = [{"slot": "FLEX_ONLY", "count": 1, "eligible": ["RB", "WR"]}]
    config = {"roster": {"starters": starters_flex_only}}
    ds = _fresh_state(rounds=1)  # 10 total picks; Monster Cheese's only pick is #4
    for _ in range(3):
        ds.log_pick_on_the_clock("Filler", position="K")  # not RB/WR -- slot stays unfilled
    assert ds.is_my_pick
    assert _remaining_my_picks(ds) == 1
    assert _mandatory_deadline_positions(ds, config) == set()


# ---------------------------------------------------------------------
# _position_cap / _redundancy_penalty / _early_round_discount
# ---------------------------------------------------------------------

def test_position_cap_reads_configured_max_for_cappable_positions():
    config = {"roster": {"position_active_limits": {"DST": {"min": 1, "max": 1}, "K": {"min": 1, "max": 3}}}}
    assert _position_cap("DST", config) == 1
    assert _position_cap("K", config) == 3


def test_position_cap_is_none_for_wr_even_if_a_combined_limit_is_configured():
    # WR_TE is a combined aggregate limit CBS's own rules page reports --
    # splitting it back into a per-position WR cap would mean guessing at
    # an interpretation nobody has confirmed, so WR is deliberately left
    # uncapped (see _CAPPABLE_POSITIONS's comment).
    config = {"roster": {"position_active_limits": {"WR_TE": {"min": 3, "max": 5}}}}
    assert _position_cap("WR", config) is None


def test_position_cap_is_none_when_not_configured():
    assert _position_cap("QB", {}) is None


def test_redundancy_penalty_squashes_once_at_cap():
    config = {"roster": {"position_active_limits": {"DST": {"max": 1}}}}
    penalty, at_cap = _redundancy_penalty("DST", {"DST": 1}, config)
    assert at_cap is True
    assert penalty == pytest.approx(0.05)


def test_redundancy_penalty_is_neutral_below_cap():
    config = {"roster": {"position_active_limits": {"DST": {"max": 1}}}}
    penalty, at_cap = _redundancy_penalty("DST", {"DST": 0}, config)
    assert at_cap is False
    assert penalty == 1.0


def test_redundancy_penalty_is_neutral_for_an_uncappable_position():
    penalty, at_cap = _redundancy_penalty("WR", {"WR": 10}, {"roster": {"position_active_limits": {}}})
    assert penalty == 1.0
    assert at_cap is False


EARLY_DISCOUNT_CONFIG = {
    "estimation_assumptions": {
        "position_early_round_discount": {
            "K": {"before_round": 17, "multiplier": 0.2},
            "DST": {"before_round": 17, "multiplier": 0.2},
        }
    }
}


def test_early_round_discount_applies_before_configured_round():
    mult, applied = _early_round_discount("K", 5, EARLY_DISCOUNT_CONFIG)
    assert applied is True
    assert mult == pytest.approx(0.2)


def test_early_round_discount_lifts_at_the_configured_round():
    mult, applied = _early_round_discount("K", 17, EARLY_DISCOUNT_CONFIG)
    assert applied is False
    assert mult == 1.0


def test_early_round_discount_does_not_apply_to_an_unconfigured_position():
    mult, applied = _early_round_discount("RB", 1, EARLY_DISCOUNT_CONFIG)
    assert mult == 1.0
    assert applied is False


def test_describe_mentions_redundancy_cap_when_top_pick_is_capped():
    score = PositionScore(
        position="DST", composite=0.01, value_raw=5.0, need_raw=0.0,
        predicted_picks=0.0, remaining_top_tier=1, remaining_players=1,
        scarcity_ratio=0.0, at_position_cap=True,
    )
    assert "active-roster max" in _describe(score, horizon=5)


def test_describe_mentions_early_round_discount_when_top_pick_is_discounted():
    score = PositionScore(
        position="K", composite=0.01, value_raw=5.0, need_raw=0.0,
        predicted_picks=0.0, remaining_top_tier=1, remaining_players=1,
        scarcity_ratio=0.0, early_round_discounted=True,
    )
    assert "not worth taking this early" in _describe(score, horizon=5)


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


def test_suggest_position_redundancy_cap_only_squashes_the_capped_positions_composite():
    # Regression test for the Monte Carlo pathology found 2026-08-26: once
    # a shallow-pool position (DST here) already meets its configured
    # active-roster max, its still-mildly-positive VOR shouldn't keep
    # outcompeting positions that actually need filling.
    ds = _fresh_state()
    ds.log_pick("Monster Cheese", "DST1", position="DST")  # fills DST's only slot -> at cap once capped
    board = _board([
        _player("DST2", "DST", vor=5.0, vor_rank=10, tier=1),
        _player("RB1", "RB", vor=3.0, vor_rank=20, tier=2),
    ])
    no_cap_config = CONFIG
    capped_config = {
        **CONFIG,
        "roster": {**CONFIG["roster"], "position_active_limits": {"DST": {"min": 1, "max": 1}}},
    }

    no_cap = suggest_position(board, ds, no_cap_config, history=None)
    capped = suggest_position(board, ds, capped_config, history=None)

    dst_no_cap = next(s for s in no_cap.all_scores if s.position == "DST")
    dst_capped = next(s for s in capped.all_scores if s.position == "DST")
    rb_no_cap = next(s for s in no_cap.all_scores if s.position == "RB")
    rb_capped = next(s for s in capped.all_scores if s.position == "RB")

    assert dst_no_cap.at_position_cap is False
    assert dst_capped.at_position_cap is True
    assert dst_capped.composite == pytest.approx(dst_no_cap.composite * 0.05)
    # RB's composite is untouched by DST's cap.
    assert rb_capped.composite == pytest.approx(rb_no_cap.composite)


def test_suggest_position_early_round_discount_only_squashes_k_before_configured_round():
    ds = _fresh_state()
    board = _board([
        _player("K1", "K", vor=5.0, vor_rank=10, tier=1),
        _player("RB1", "RB", vor=3.0, vor_rank=20, tier=2),
    ])
    discount_config = {**CONFIG, "estimation_assumptions": EARLY_DISCOUNT_CONFIG["estimation_assumptions"]}

    no_discount = suggest_position(board, ds, CONFIG, history=None)
    discounted = suggest_position(board, ds, discount_config, history=None)

    k_no_discount = next(s for s in no_discount.all_scores if s.position == "K")
    k_discounted = next(s for s in discounted.all_scores if s.position == "K")
    rb_no_discount = next(s for s in no_discount.all_scores if s.position == "RB")
    rb_discounted = next(s for s in discounted.all_scores if s.position == "RB")

    assert k_no_discount.early_round_discounted is False
    assert k_discounted.early_round_discounted is True
    assert k_discounted.composite == pytest.approx(k_no_discount.composite * 0.2)
    assert rb_discounted.composite == pytest.approx(rb_no_discount.composite)


def test_suggest_position_forces_mandatory_fill_over_everything_else():
    # Regression test for the 2026-08-26 Monte Carlo finding: with the
    # redundancy fix above in place, some simulated 22-round drafts went
    # all the way to the end having NEVER drafted a single QB, because a
    # deep QB replacement pool means QB's raw VOR rarely craters enough to
    # win the composite against RB/WR. This asserts the actual guarantee:
    # once I'm on my LAST chance to ever fill a mandatory dedicated slot,
    # it wins regardless of how lopsided the value comparison is.
    ds = _fresh_state(rounds=2)  # Monster Cheese picks at overall 4 and 17
    for _ in range(16):
        ds.log_pick_on_the_clock("Filler", position="RB")
    assert ds.next_overall_pick == 17
    board = _board([
        _player("Elite WR", "WR", vor=500.0, vor_rank=1, tier=1),  # overwhelming value elsewhere
        _player("Mediocre QB", "QB", vor=1.0, vor_rank=80, tier=3),
    ])
    suggestion = suggest_position(board, ds, CONFIG, history=None)
    assert suggestion.recommended_position == "QB"
    qb_score = next(s for s in suggestion.all_scores if s.position == "QB")
    assert qb_score.mandatory_fill is True
    assert "out of picks left" in suggestion.reasoning


def test_suggest_position_does_not_force_anything_when_picks_still_remain():
    ds = _fresh_state()  # 15 rounds -- nowhere near a deadline
    board = _board([
        _player("Elite WR", "WR", vor=500.0, vor_rank=1, tier=1),
        _player("Mediocre QB", "QB", vor=1.0, vor_rank=80, tier=3),
    ])
    suggestion = suggest_position(board, ds, CONFIG, history=None)
    assert suggestion.recommended_position == "WR"


def test_suggest_position_never_recommends_a_capped_position_when_a_legal_alternative_exists():
    # Regression test for the 2026-08-26 Monte Carlo finding: a flat
    # REDUNDANCY_PENALTY squash on the composite isn't enough on its own
    # -- a shallow-pool position's VOR can stay positive long after a
    # skill position's has gone deeply negative past replacement level,
    # so the squashed composite can still numerically win. This asserts
    # the actual guarantee: a capped position is never recommended over a
    # legal alternative, no matter how the raw numbers compare.
    ds = _fresh_state()
    ds.log_pick("Monster Cheese", "DST1", position="DST")  # fills DST's only slot -> at cap
    board = _board([
        _player("DST2", "DST", vor=100.0, vor_rank=1, tier=1),
        _player("RB1", "RB", vor=-50.0, vor_rank=90, tier=3),  # deep past replacement level
    ])
    config = {
        **CONFIG,
        "roster": {**CONFIG["roster"], "position_active_limits": {"DST": {"min": 1, "max": 1}}},
    }
    suggestion = suggest_position(board, ds, config, history=None)
    dst_score = next(s for s in suggestion.all_scores if s.position == "DST")
    assert dst_score.at_position_cap is True
    assert dst_score.composite > 0  # the squash alone would still make DST look attractive
    assert suggestion.recommended_position == "RB"  # hard exclusion wins anyway


def test_suggest_position_falls_back_to_a_capped_position_when_everything_is_capped():
    ds = _fresh_state()
    ds.log_pick("Monster Cheese", "DST1", position="DST")
    board = _board([_player("DST2", "DST", vor=5.0, vor_rank=1, tier=1)])
    config = {
        **CONFIG,
        "roster": {**CONFIG["roster"], "position_active_limits": {"DST": {"min": 1, "max": 1}}},
    }
    suggestion = suggest_position(board, ds, config, history=None)
    assert suggestion.recommended_position == "DST"
    assert suggestion.all_scores[0].at_position_cap is True


def test_suggest_position_zeroes_need_for_a_capped_position_even_if_a_flex_slot_is_still_eligible():
    # TE's dedicated slot filling doesn't zero its need on its own -- the
    # STARTERS fixture's WR_TE_FLEX slot is also TE-eligible, so
    # my_position_need() alone keeps giving TE a small residual need
    # weight forever. Once TE is capped, that residual need should be
    # zeroed outright, not just have its composite squashed.
    ds = _fresh_state()
    ds.log_pick("Monster Cheese", "TE1", position="TE")  # fills TE's only dedicated slot -> at cap
    config = {
        **CONFIG,
        "roster": {**CONFIG["roster"], "position_active_limits": {"TE": {"min": 1, "max": 1}}},
    }
    # Sanity check: WITHOUT the cap wired in, TE still shows nonzero need
    # because WR_TE_FLEX (eligible WR/TE) is still open.
    need_uncapped = my_position_need(ds, CONFIG)
    assert need_uncapped["TE"] > 0

    board = _board([
        _player("TE2", "TE", vor=1.0, vor_rank=30, tier=2),
        _player("WR1", "WR", vor=1.0, vor_rank=31, tier=2),
    ])
    suggestion = suggest_position(board, ds, config, history=None)
    te_score = next(s for s in suggestion.all_scores if s.position == "TE")
    assert te_score.need_raw == 0.0
    assert te_score.at_position_cap is True


def test_suggest_position_early_round_discount_lifts_once_past_the_configured_round():
    ds = _fresh_state(rounds=22)
    for _ in range(170):  # completes rounds 1-17; the 171st pick starts round 18
        ds.log_pick_on_the_clock("Filler", position="RB")
    current_round, _ = ds.round_and_slot_for_pick(ds.next_overall_pick)
    assert current_round == 18
    board = _board([_player("K1", "K", vor=5.0, vor_rank=10, tier=1)])
    discount_config = {**CONFIG, "estimation_assumptions": EARLY_DISCOUNT_CONFIG["estimation_assumptions"]}
    suggestion = suggest_position(board, ds, discount_config, history=None)
    k_score = next(s for s in suggestion.all_scores if s.position == "K")
    assert k_score.early_round_discounted is False


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
