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
    _not_before_round_blocked,
    _position_cap,
    _redundancy_penalty,
    _remaining_my_picks,
    _remaining_my_picks_before_round,
    _round_based_quota_positions,
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
# _remaining_my_picks_before_round / _round_based_quota_positions
# ---------------------------------------------------------------------

def test_remaining_my_picks_before_round_counts_only_picks_at_or_before_the_limit():
    ds = _fresh_state(rounds=3)  # Monster Cheese picks at overall 4, 17, 24
    assert _remaining_my_picks_before_round(ds, round_limit=1) == 1
    assert _remaining_my_picks_before_round(ds, round_limit=2) == 2
    assert _remaining_my_picks_before_round(ds, round_limit=3) == 3


def test_remaining_my_picks_before_round_is_zero_once_past_the_deadline_round():
    ds = _fresh_state(rounds=3)
    for _ in range(20):  # picks 1-20 logged; next pick (21) is round 3
        ds.log_pick_on_the_clock("Filler", position="RB")
    assert _remaining_my_picks_before_round(ds, round_limit=2) == 0


QUOTA_CONFIG = {
    **CONFIG,
    "estimation_assumptions": {
        "round_based_fill_targets": [
            {"slot": "QB", "eligible": ["QB"], "count": 2, "by_round": 7}
        ]
    },
}


def test_round_based_quota_positions_empty_when_target_already_met():
    ds = _fresh_state()
    ds.log_pick("Monster Cheese", "QB1", position="QB")
    ds.log_pick("Monster Cheese", "QB2", position="QB")
    assert _round_based_quota_positions(ds, QUOTA_CONFIG) == set()


def test_round_based_quota_positions_empty_when_deadline_round_already_passed():
    ds = _fresh_state(rounds=15)
    for _ in range(80):  # well past round 7
        ds.log_pick_on_the_clock("Filler", position="RB")
    assert _round_based_quota_positions(ds, QUOTA_CONFIG) == set()


def test_round_based_quota_positions_not_yet_urgent_with_plenty_of_chances_left():
    ds = _fresh_state(rounds=15)  # 7 rounds of chances ahead, 0 QBs drafted -- fine for now
    assert _round_based_quota_positions(ds, QUOTA_CONFIG) == set()


def test_round_based_quota_positions_flags_qb_on_the_last_realistic_chance():
    ds = _fresh_state(rounds=15)
    for _ in range(3):
        ds.log_pick_on_the_clock("Filler", position="RB")  # picks 1-3, other teams
    ds.log_pick_on_the_clock("QB1", position="QB")  # pick 4 -- Monster Cheese's round-1 pick
    for _ in range(53):
        ds.log_pick_on_the_clock("Filler", position="RB")  # picks 5-57
    assert ds.next_overall_pick == 58
    # Monster Cheese has 1 QB; only 1 more Monster Cheese pick (64, round 7)
    # remains before the round-7 deadline -- last realistic chance for QB2.
    assert "QB" in _round_based_quota_positions(ds, QUOTA_CONFIG)


def test_round_based_quota_positions_does_not_double_count_overlapping_categories():
    # Two categories that both accept RB (a dedicated RB category and a
    # broader RB/WR/TE category) must draw from the SAME pool of drafted
    # RBs, not each count the same picks independently.
    targets = [
        {"slot": "RB_REQUIREMENT", "eligible": ["RB"], "count": 2, "by_round": 20},
        {"slot": "RB_WR_TE_REQUIREMENT", "eligible": ["RB", "WR", "TE"], "count": 1, "by_round": 20},
    ]
    config = {**CONFIG, "estimation_assumptions": {"round_based_fill_targets": targets}}
    ds = _fresh_state(rounds=20)
    ds.log_pick("Monster Cheese", "RB1", position="RB")
    ds.log_pick("Monster Cheese", "RB2", position="RB")
    ds.log_pick("Monster Cheese", "RB3", position="RB")
    # 3 drafted RBs: the most-restrictive dedicated RB category (needs 2)
    # claims 2 of them first, leaving 1 RB to satisfy the broader
    # RB/WR/TE category (needs 1) -- both fully met, nothing double-spent.
    assert _round_based_quota_positions(ds, config) == set()


def test_round_based_quota_positions_groups_categories_sharing_one_deadline():
    # Neither category looks urgent when checked against the FULL
    # remaining-picks-before-deadline count on its own (3 < 5 for each),
    # but their COMBINED remaining need (6) already exceeds the combined
    # remaining picks (5) -- checking them as a group must catch this even
    # though no single category is individually out of slack.
    targets = [
        {"slot": "K", "eligible": ["K"], "count": 3, "by_round": 5},
        {"slot": "DEF", "eligible": ["DST"], "count": 3, "by_round": 5},
    ]
    config = {**CONFIG, "estimation_assumptions": {"round_based_fill_targets": targets}}
    ds = _fresh_state(rounds=15)  # 5 Monster Cheese picks remain before round 5
    urgent = _round_based_quota_positions(ds, config)
    assert urgent == {"K", "DST"}


def test_round_based_quota_positions_grouped_categories_not_urgent_with_real_slack():
    # Same shared-deadline shape as above, but with real slack: combined
    # need (4) stays under combined remaining picks (5).
    targets = [
        {"slot": "K", "eligible": ["K"], "count": 2, "by_round": 5},
        {"slot": "DEF", "eligible": ["DST"], "count": 2, "by_round": 5},
    ]
    config = {**CONFIG, "estimation_assumptions": {"round_based_fill_targets": targets}}
    ds = _fresh_state(rounds=15)
    assert _round_based_quota_positions(ds, config) == set()


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

NOT_BEFORE_ROUND_CONFIG = {
    "estimation_assumptions": {
        "position_not_before_round": {
            "K": {"not_before_round": 17, "starting_at_count": 1},
            "DST": {"not_before_round": 17, "starting_at_count": 2},
        }
    }
}


def test_not_before_round_blocked_applies_to_every_k_before_the_configured_round():
    # K's starting_at_count is 1 -- blocks the 1st K just as much as the 2nd.
    assert _not_before_round_blocked("K", 5, {}, NOT_BEFORE_ROUND_CONFIG) is True
    assert _not_before_round_blocked("K", 5, {"K": 1}, NOT_BEFORE_ROUND_CONFIG) is True


def test_not_before_round_blocked_lifts_at_the_configured_round():
    assert _not_before_round_blocked("K", 17, {}, NOT_BEFORE_ROUND_CONFIG) is False


def test_not_before_round_blocked_leaves_the_first_dst_unrestricted():
    # DST's starting_at_count is 2 -- the 1st DST is untouched, only the
    # 2nd-and-later is blocked.
    assert _not_before_round_blocked("DST", 5, {}, NOT_BEFORE_ROUND_CONFIG) is False
    assert _not_before_round_blocked("DST", 5, {"DST": 1}, NOT_BEFORE_ROUND_CONFIG) is True


def test_not_before_round_blocked_does_not_apply_to_an_unconfigured_position():
    assert _not_before_round_blocked("RB", 1, {}, NOT_BEFORE_ROUND_CONFIG) is False


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


def test_describe_mentions_not_before_round_floor_when_top_pick_is_blocked():
    score = PositionScore(
        position="K", composite=0.01, value_raw=5.0, need_raw=0.0,
        predicted_picks=0.0, remaining_top_tier=1, remaining_players=1,
        scarcity_ratio=0.0, not_before_round_blocked=True,
    )
    assert "can't come this early" in _describe(score, horizon=5)


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


def test_suggest_position_never_recommends_an_early_round_discounted_position_when_a_clean_alternative_exists():
    # Regression test for a second Monte Carlo finding (2026-08-26): the
    # early-round discount used to be squash-only, and K/DST kept getting
    # recommended in rounds 11-15 anyway once every other position's need
    # was satisfied and its value had gone negative -- the same failure
    # mode the redundancy cap had before it was hardened. This asserts
    # the fix: a discounted position loses to a legal, non-negative
    # alternative even when its own squashed composite is still positive.
    ds = _fresh_state()
    board = _board([
        _player("K1", "K", vor=100.0, vor_rank=1, tier=1),
        _player("RB1", "RB", vor=1.0, vor_rank=50, tier=3),
    ])
    discount_config = {**CONFIG, "estimation_assumptions": EARLY_DISCOUNT_CONFIG["estimation_assumptions"]}
    suggestion = suggest_position(board, ds, discount_config, history=None)
    k_score = next(s for s in suggestion.all_scores if s.position == "K")
    assert k_score.early_round_discounted is True
    assert k_score.composite > 0  # the squash alone would still make K look attractive
    assert suggestion.recommended_position == "RB"  # hard exclusion wins anyway


def test_suggest_position_falls_back_to_a_discounted_position_when_nothing_else_is_available():
    ds = _fresh_state()
    board = _board([_player("K1", "K", vor=5.0, vor_rank=1, tier=1)])
    discount_config = {**CONFIG, "estimation_assumptions": EARLY_DISCOUNT_CONFIG["estimation_assumptions"]}
    suggestion = suggest_position(board, ds, discount_config, history=None)
    assert suggestion.recommended_position == "K"
    assert suggestion.all_scores[0].early_round_discounted is True


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


def test_suggest_position_weight_overrides_change_the_composite_blend():
    ds = _fresh_state()
    board = _board([
        _player("RB1", "RB", vor=10.0, vor_rank=1, tier=1),
        _player("WR1", "WR", vor=1.0, vor_rank=2, tier=1),
    ])
    default = suggest_position(board, ds, CONFIG, history=None)
    value_only = suggest_position(
        board, ds, CONFIG, history=None, value_weight=1.0, need_weight=0.0, scarcity_weight=0.0,
    )
    rb_default = next(s for s in default.all_scores if s.position == "RB")
    rb_value_only = next(s for s in value_only.all_scores if s.position == "RB")
    # RB is the peak VOR (10.0) among the two, so a pure value_weight=1.0
    # blend should give it exactly value_norm==1.0 as its composite.
    assert rb_value_only.composite == pytest.approx(1.0)
    assert rb_value_only.composite != rb_default.composite


def test_suggest_position_forces_quota_deadline_position_over_everything_else():
    ds = _fresh_state(rounds=15)
    for _ in range(3):
        ds.log_pick_on_the_clock("Filler", position="RB")
    ds.log_pick_on_the_clock("QB1", position="QB")  # pick 4
    for _ in range(53):
        ds.log_pick_on_the_clock("Filler", position="RB")
    assert ds.next_overall_pick == 58
    board = _board([
        _player("Elite WR", "WR", vor=500.0, vor_rank=1, tier=1),  # overwhelming value elsewhere
        _player("Mediocre QB", "QB", vor=1.0, vor_rank=80, tier=3),
    ])
    suggestion = suggest_position(board, ds, QUOTA_CONFIG, history=None)
    assert suggestion.recommended_position == "QB"
    qb_score = next(s for s in suggestion.all_scores if s.position == "QB")
    assert qb_score.quota_deadline is True
    assert "round-based target" in suggestion.reasoning


def test_suggest_position_does_not_force_qb_without_a_configured_quota():
    # Same scenario as above, but with plain CONFIG (no
    # round_based_fill_targets) -- proves the override above is actually
    # coming from the quota mechanism, not something else.
    ds = _fresh_state(rounds=15)
    for _ in range(3):
        ds.log_pick_on_the_clock("Filler", position="RB")
    ds.log_pick_on_the_clock("QB1", position="QB")
    for _ in range(53):
        ds.log_pick_on_the_clock("Filler", position="RB")
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


def test_suggest_position_quota_group_prefers_uncapped_member_over_capped_one():
    # Regression test for the 2026-08-27 Monte Carlo finding: Monster
    # Cheese drafted up to 6 TEs in a single simulated draft, well past
    # the configured position_active_limits max of 2. Root cause: this
    # league's real requirements bundle several categories under one
    # shared round-20 deadline (see config's round_based_fill_targets), so
    # an unfilled "5 WR or TE" category gets grouped into one urgent
    # bucket with TE eligible alongside WR -- and unlike the ordinary
    # (non-must-fill) ranking path, the must-fill override tier used to
    # pick the single highest RAW composite across that whole bucket with
    # no cap check at all. Once TE hit its cap its composite is squashed
    # by REDUNDANCY_PENALTY (0.05x), but a shallow position's VOR can stay
    # mildly positive long after WR's has cratered past replacement level
    # in the late rounds this quota tends to fire in -- so the squashed
    # TE composite still numerically beat a deeply negative WR composite.
    ds = _fresh_state(rounds=20)
    ds.log_pick("Monster Cheese", "TE1", position="TE")
    ds.log_pick("Monster Cheese", "TE2", position="TE")  # TE now at its cap (max 2)
    # 170 filler picks -> exactly 3 Monster Cheese picks left before round
    # 20's deadline, matching this category's remaining need (5 - 2
    # already-TE = 3) precisely enough to make the group genuinely urgent
    # (asserted below via quota_deadline) -- not just numerically close.
    for _ in range(170):
        ds.log_pick_on_the_clock("Filler", position="RB")
    board = _board([
        _player("TE3", "TE", vor=1.0, vor_rank=40, tier=3),  # thin pool never craters
        _player("WR1", "WR", vor=-80.0, vor_rank=200, tier=5),  # deep past replacement level
    ])
    config = {
        **CONFIG,
        "roster": {**CONFIG["roster"], "position_active_limits": {"TE": {"min": 1, "max": 2}}},
        "estimation_assumptions": {
            "round_based_fill_targets": [
                {"slot": "WR_TE_REQUIREMENT", "eligible": ["WR", "TE"], "count": 5, "by_round": 20},
            ]
        },
    }
    suggestion = suggest_position(board, ds, config, history=None)
    te_score = next(s for s in suggestion.all_scores if s.position == "TE")
    wr_score = next(s for s in suggestion.all_scores if s.position == "WR")
    assert te_score.quota_deadline is True and wr_score.quota_deadline is True  # group is genuinely urgent
    assert te_score.at_position_cap is True
    assert te_score.composite > 0  # the squash alone would still make TE look attractive
    assert suggestion.recommended_position == "WR"  # prefers the uncapped quota member anyway


def test_suggest_position_quota_group_falls_back_to_capped_member_if_that_is_all_thats_urgent():
    # Sole-eligible mandatory category (TE_MANDATORY-style, eligible=[TE]
    # only) with no uncapped alternative in the group -- the requirement
    # itself can't be skipped, so this must still force TE despite the cap.
    ds = _fresh_state(rounds=20)
    ds.log_pick("Monster Cheese", "TE1", position="TE")
    ds.log_pick("Monster Cheese", "TE2", position="TE")  # TE already at cap
    # 185 filler picks -> exactly 1 Monster Cheese pick left before round
    # 20's deadline, matching this category's remaining need (3 - 2
    # already-TE = 1) exactly, so the group is genuinely urgent.
    for _ in range(185):
        ds.log_pick_on_the_clock("Filler", position="RB")
    board = _board([
        _player("TE3", "TE", vor=1.0, vor_rank=40, tier=3),
        _player("WR1", "WR", vor=500.0, vor_rank=1, tier=1),  # not part of this category at all
    ])
    config = {
        **CONFIG,
        "roster": {**CONFIG["roster"], "position_active_limits": {"TE": {"min": 1, "max": 2}}},
        "estimation_assumptions": {
            "round_based_fill_targets": [
                {"slot": "TE_MANDATORY", "eligible": ["TE"], "count": 3, "by_round": 20},
            ]
        },
    }
    suggestion = suggest_position(board, ds, config, history=None)
    te_score = next(s for s in suggestion.all_scores if s.position == "TE")
    assert te_score.quota_deadline is True  # group is genuinely urgent
    assert suggestion.recommended_position == "TE"


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


def test_suggest_position_never_recommends_k_before_round_17_when_a_clean_alternative_exists():
    # Regression test for the league-manager's 2026-08-28 request: "For our
    # team only, add a rule that the second defense and the 2 kickers
    # cannot come before round 17." Same hard-exclusion shape as the
    # early-round-discount tests above, but with no fallback-via-squash --
    # this is an absolute floor, not a value nudge.
    ds = _fresh_state(rounds=20)
    board = _board([
        _player("K1", "K", vor=500.0, vor_rank=1, tier=1),
        _player("RB1", "RB", vor=1.0, vor_rank=80, tier=3),
    ])
    config = {**CONFIG, "estimation_assumptions": NOT_BEFORE_ROUND_CONFIG["estimation_assumptions"]}
    suggestion = suggest_position(board, ds, config, history=None)
    k_score = next(s for s in suggestion.all_scores if s.position == "K")
    assert k_score.not_before_round_blocked is True
    assert k_score.composite > 0  # the raw composite would clearly win otherwise
    assert suggestion.recommended_position == "RB"


def test_suggest_position_falls_back_to_a_not_before_round_blocked_position_when_nothing_else_is_available():
    ds = _fresh_state(rounds=20)
    board = _board([_player("K1", "K", vor=5.0, vor_rank=1, tier=1)])
    config = {**CONFIG, "estimation_assumptions": NOT_BEFORE_ROUND_CONFIG["estimation_assumptions"]}
    suggestion = suggest_position(board, ds, config, history=None)
    assert suggestion.recommended_position == "K"
    assert suggestion.all_scores[0].not_before_round_blocked is True


def test_suggest_position_lets_the_first_dst_through_but_blocks_the_second():
    config = {**CONFIG, "estimation_assumptions": NOT_BEFORE_ROUND_CONFIG["estimation_assumptions"]}
    board = _board([
        _player("DST1", "DST", vor=500.0, vor_rank=1, tier=1),
        _player("RB1", "RB", vor=1.0, vor_rank=80, tier=3),
    ])
    ds = _fresh_state(rounds=20)
    suggestion = suggest_position(board, ds, config, history=None)
    dst_score = next(s for s in suggestion.all_scores if s.position == "DST")
    assert dst_score.not_before_round_blocked is False
    assert suggestion.recommended_position == "DST"  # 1st DST is unrestricted

    ds.log_pick("Monster Cheese", "DST1", position="DST")
    board2 = _board([
        _player("DST2", "DST", vor=500.0, vor_rank=1, tier=1),
        _player("RB1", "RB", vor=1.0, vor_rank=80, tier=3),
    ])
    suggestion2 = suggest_position(board2, ds, config, history=None)
    dst_score2 = next(s for s in suggestion2.all_scores if s.position == "DST")
    assert dst_score2.not_before_round_blocked is True  # now drafting the 2nd
    assert suggestion2.recommended_position == "RB"


def test_suggest_position_not_before_round_floor_lifts_once_past_the_configured_round():
    ds = _fresh_state(rounds=20)
    for _ in range(160):  # completes rounds 1-16; the 161st pick starts round 17
        ds.log_pick_on_the_clock("Filler", position="RB")
    current_round, _ = ds.round_and_slot_for_pick(ds.next_overall_pick)
    assert current_round == 17
    board = _board([_player("K1", "K", vor=5.0, vor_rank=10, tier=1)])
    config = {**CONFIG, "estimation_assumptions": NOT_BEFORE_ROUND_CONFIG["estimation_assumptions"]}
    suggestion = suggest_position(board, ds, config, history=None)
    k_score = next(s for s in suggestion.all_scores if s.position == "K")
    assert k_score.not_before_round_blocked is False


QUOTA_AND_FLOOR_CONFIG = {
    **CONFIG,
    "estimation_assumptions": {
        "round_based_fill_targets": [
            {"slot": "K_REQ", "eligible": ["K"], "count": 2, "by_round": 17},
        ],
        "position_not_before_round": {
            "K": {"not_before_round": 17, "starting_at_count": 1},
        },
    },
}


def test_suggest_position_not_before_round_floor_overrides_a_quota_deadline():
    # Synthetic scenario: production config's real K quota deadline is
    # round 20 -- three rounds after this floor lifts -- so this exact
    # collision never happens in a real draft (see
    # _not_before_round_blocked()'s docstring). Still worth proving the
    # override logic directly, independent of whether today's config
    # happens to exercise it.
    ds = _fresh_state(rounds=17)
    for _ in range(150):  # completes rounds 1-15; the 151st pick starts round 16
        ds.log_pick_on_the_clock("Filler", position="RB")
    current_round, _ = ds.round_and_slot_for_pick(ds.next_overall_pick)
    assert current_round == 16
    board = _board([
        _player("K1", "K", vor=500.0, vor_rank=1, tier=1),
        _player("RB1", "RB", vor=1.0, vor_rank=80, tier=3),
    ])
    suggestion = suggest_position(board, ds, QUOTA_AND_FLOOR_CONFIG, history=None)
    k_score = next(s for s in suggestion.all_scores if s.position == "K")
    assert k_score.quota_deadline is True  # the deadline really is urgent here
    assert k_score.not_before_round_blocked is True  # floor still active (round 16 < 17)
    assert suggestion.recommended_position == "RB"  # floor wins over the deadline


def test_suggest_position_falls_back_to_a_blocked_quota_position_if_it_is_the_only_urgent_option():
    ds = _fresh_state(rounds=17)
    for _ in range(150):
        ds.log_pick_on_the_clock("Filler", position="RB")
    board = _board([_player("K1", "K", vor=5.0, vor_rank=1, tier=1)])
    suggestion = suggest_position(board, ds, QUOTA_AND_FLOOR_CONFIG, history=None)
    assert suggestion.recommended_position == "K"
    assert suggestion.all_scores[0].not_before_round_blocked is True


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
