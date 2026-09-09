from src.waiver_recommendations import (
    FreeAgent,
    RosterPlayer,
    build_recommendations,
)

def _by_source(roster, free_agents):
    """Test helper: wraps a flat roster into the per-source dict
    build_recommendations expects, using the SAME roster valuation for
    every source in free_agents -- fine for these tests, which don't
    care about CBS vs FantasyPoints roster-side valuation differing."""
    return {source: roster for source in free_agents}


STARTERS = [
    {"slot": "QB", "count": 1, "eligible": ["QB"]},
    {"slot": "RB", "count": 2, "eligible": ["RB"]},
    {"slot": "FLEX", "count": 1, "eligible": ["RB", "WR", "TE"]},
]


def test_bye_gap_recommends_best_eligible_fa_for_empty_slot():
    # Only 1 RB rostered (bye this week) against 2 RB slots + a FLEX that
    # could also take an RB -- the solver should come back with at least
    # one genuinely empty slot, and the engine should recommend the best
    # available RB free agent for it.
    roster = [
        RosterPlayer("QB1", "QB", week_points=20.0, is_starter=True),
        RosterPlayer("RB1", "RB", week_points=0.0, is_bye=True, is_starter=True),
        RosterPlayer("WR1", "WR", week_points=8.0, is_starter=True),
    ]
    free_agents = {
        "CBS": [
            FreeAgent("FA RB Good", "RB", "ABC", week_points=15.0),
            FreeAgent("FA RB Bad", "RB", "DEF", week_points=5.0),
            FreeAgent("FA WR", "WR", "GHI", week_points=25.0),
        ]
    }
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    bye_gap_recs = [r for r in recs if r.category == "bye_gap"]
    assert bye_gap_recs, "expected at least one bye_gap recommendation"
    # The best RB free agent should show up for at least one empty slot.
    assert any(r.add_name == "FA RB Good" for r in bye_gap_recs)


def test_bye_gap_produces_nothing_without_week_points():
    # No weekly matchup data captured for the selected week -- roster
    # players carry no week_points, so tier 1 can't run (silently
    # produces nothing rather than a bogus/empty-pool result).
    roster = [RosterPlayer("QB1", "QB", week_points=None, is_starter=True)]
    free_agents = {"CBS": [FreeAgent("FA QB", "QB", "ABC", week_points=10.0)]}
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    assert not any(r.category == "bye_gap" for r in recs)


def test_season_upgrade_recommends_fa_beating_weakest_comparable_player():
    roster = [
        RosterPlayer("Weak WR", "WR", season_points=50.0, is_starter=True),
        RosterPlayer("Strong WR", "WR", season_points=200.0, is_starter=True),
    ]
    free_agents = {
        "CBS": [
            FreeAgent("Better WR", "WR", "ABC", season_points=120.0),
            FreeAgent("Worse WR", "WR", "DEF", season_points=10.0),
        ]
    }
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    upgrades = {r.add_name: r for r in recs if r.category == "season_upgrade"}
    assert "Better WR" in upgrades
    assert upgrades["Better WR"].drop_name == "Weak WR"
    assert "Worse WR" not in upgrades  # doesn't beat anyone


def test_season_upgrade_skips_free_agent_already_on_roster():
    # A name collision shouldn't recommend "adding" a player you already have.
    roster = [RosterPlayer("Same Name", "WR", season_points=50.0, is_starter=True)]
    free_agents = {"CBS": [FreeAgent("Same Name", "WR", "ABC", season_points=999.0)]}
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    assert not recs


def test_bench_depth_only_fires_with_open_roster_room():
    # Only 1 RB rostered against a 2-RB slot (thin) -- but roster is at
    # the 27-player cap, so bench_depth (add without dropping) should
    # NOT fire; full_roster_swap might, but that's a different category.
    roster = [RosterPlayer(f"P{i}", "RB" if i == 0 else "K", season_points=10.0) for i in range(27)]
    free_agents = {"CBS": [FreeAgent("FA RB", "RB", "ABC", season_points=50.0)]}
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    assert not any(r.category == "bench_depth" for r in recs)


def test_bench_depth_fires_when_position_thin_and_room_open():
    roster = [RosterPlayer("Only RB", "RB", season_points=40.0)]
    free_agents = {"CBS": [FreeAgent("Depth RB", "RB", "ABC", season_points=30.0)]}
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    depth_recs = [r for r in recs if r.category == "bench_depth"]
    assert any(r.add_name == "Depth RB" for r in depth_recs)
    assert depth_recs[0].drop_name is None  # add without dropping


def test_full_roster_swap_only_fires_at_cap_and_names_both_players():
    # Free agent is a WR, but nobody on this (K-only) 27-man roster is
    # WR-eligible -- season_upgrade (tier 2) has no comparable player to
    # compare against and stays silent, so this exercises full_roster_swap
    # (tier 4) distinctly rather than being shadowed by tier 2's own
    # drop-name suggestion.
    roster = [RosterPlayer(f"Bench{i}", "K", season_points=5.0) for i in range(27)]
    roster[0] = RosterPlayer("Weakest Bench", "K", season_points=1.0, is_starter=False)
    free_agents = {"CBS": [FreeAgent("Great FA", "WR", "ABC", season_points=50.0)]}
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    swaps = [r for r in recs if r.category == "full_roster_swap"]
    assert swaps
    assert swaps[0].add_name == "Great FA"
    assert swaps[0].drop_name == "Weakest Bench"


def test_recommendations_tagged_with_source():
    roster = [RosterPlayer("Weak WR", "WR", season_points=10.0, is_starter=True)]
    free_agents = {
        "CBS": [FreeAgent("CBS Pick", "WR", "ABC", season_points=99.0)],
        "FantasyPoints": [FreeAgent("FP Pick", "WR", "DEF", season_points=88.0)],
    }
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    sources = {r.add_name: r.source for r in recs}
    assert sources["CBS Pick"] == "CBS"
    assert sources["FP Pick"] == "FantasyPoints"


def test_same_player_recommended_by_multiple_sources_not_deduped_across_sources():
    roster = [RosterPlayer("Weak WR", "WR", season_points=10.0, is_starter=True)]
    free_agents = {
        "CBS": [FreeAgent("Star WR", "WR", "ABC", season_points=99.0)],
        "FantasyPoints": [FreeAgent("Star WR", "WR", "ABC", season_points=95.0)],
    }
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    star_wr_recs = [r for r in recs if r.add_name == "Star WR"]
    assert len(star_wr_recs) == 2
    assert {r.source for r in star_wr_recs} == {"CBS", "FantasyPoints"}


def test_player_qualifying_for_multiple_tiers_keeps_only_highest_priority():
    # A free agent that would both fill an empty slot (tier 1) AND count
    # as a season upgrade (tier 2) should appear only once, as bye_gap
    # (the higher-priority category).
    roster = [
        RosterPlayer("QB1", "QB", week_points=20.0, season_points=200.0, is_starter=True),
        RosterPlayer("RB1", "RB", week_points=0.0, season_points=50.0, is_bye=True, is_starter=True),
        RosterPlayer("RB2", "RB", week_points=10.0, season_points=60.0, is_starter=True),
    ]
    free_agents = {
        "CBS": [FreeAgent("Great RB", "RB", "ABC", week_points=30.0, season_points=300.0)],
    }
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    great_rb_recs = [r for r in recs if r.add_name == "Great RB"]
    assert len(great_rb_recs) == 1
    assert great_rb_recs[0].category == "bye_gap"


def test_dual_eligible_position_matches_either_slot():
    # "RB-TE" (dash-joined, matching src.lineup_value's convention) should
    # be treated as eligible for a TE comparison the same as a pure TE.
    roster = [RosterPlayer("Weak TE", "TE", season_points=20.0, is_starter=True)]
    free_agents = {"CBS": [FreeAgent("Dual Player", "RB-TE", "ABC", season_points=80.0)]}
    recs = build_recommendations(_by_source(roster, free_agents), free_agents, STARTERS, roster_total_max=27)
    assert any(r.add_name == "Dual Player" and r.drop_name == "Weak TE" for r in recs)


def test_empty_roster_and_no_free_agents_produce_no_crash():
    assert build_recommendations({}, {}, STARTERS, roster_total_max=27) == []
    assert build_recommendations({"CBS": []}, {"CBS": []}, STARTERS, roster_total_max=27) == []
