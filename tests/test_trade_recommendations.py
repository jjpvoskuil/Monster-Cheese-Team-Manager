from src.trade_recommendations import TeamPlayer, combined_slot_count, find_trades

STARTERS = [
    {"slot": "QB", "count": 1, "eligible": ["QB"]},
    {"slot": "RB", "count": 2, "eligible": ["RB"]},
]


def test_combined_slot_count_sums_across_eligible_slots():
    starters = [
        {"slot": "TE", "count": 1, "eligible": ["TE"]},
        {"slot": "WR_TE_FLEX", "count": 3, "eligible": ["WR", "TE"]},
    ]
    counts = combined_slot_count(starters)
    assert counts == {"TE": 4, "WR": 3}


def test_complementary_trade_is_proposed():
    # I have a surplus QB (only 1 QB slot needed, I roster 2) and a
    # numeric RB shortage (need 2, roster 1). Rival has a weak starting
    # QB (below replacement) and a surplus RB (needs 2, rosters 3).
    # FantasyPoints rates the surplus RB much higher than CBS does --
    # deliberately, to also exercise the "FantasyPoints overvaluing vs
    # CBS" flag this module exists to guard against.
    my_roster = [
        TeamPlayer("QB Starter", "QB", "AAA", fp_vor=50.0, cbs_vor=50.0),
        TeamPlayer("QB Spare", "QB", "BBB", fp_vor=10.0, cbs_vor=15.0),
        TeamPlayer("RB Starter", "RB", "CCC", fp_vor=-5.0, cbs_vor=-5.0),
    ]
    rival_roster = [
        TeamPlayer("Weak QB", "QB", "DDD", fp_vor=-10.0, cbs_vor=-10.0),
        TeamPlayer("RB1", "RB", "EEE", fp_vor=20.0, cbs_vor=40.0),
        TeamPlayer("RB2", "RB", "FFF", fp_vor=15.0, cbs_vor=30.0),
        TeamPlayer("RB Spare", "RB", "GGG", fp_vor=60.0, cbs_vor=5.0),
    ]
    rosters = {"Me": my_roster, "Rival": rival_roster}
    trades = find_trades("Me", rosters, STARTERS)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.other_team == "Rival"
    assert [p.name for p in trade.give] == ["QB Spare"]
    assert [p.name for p in trade.get] == ["RB Spare"]
    assert trade.fp_gain_mine == 50.0   # 60 - 10
    assert trade.cbs_gain_theirs == 10.0  # 15 - 5
    assert trade.cbs_gain_mine == -10.0   # 5 - 15 -- CBS would say I LOSE value
    # even though FantasyPoints says I gain a lot -- exactly the discrepancy
    # the league manager asked to be able to see.


def test_no_complementary_need_surplus_produces_no_trade():
    # Both teams are fine at every position -- no need anywhere, so
    # nothing should be proposed regardless of raw VOR differences.
    my_roster = [
        TeamPlayer("QB1", "QB", "AAA", fp_vor=50.0, cbs_vor=50.0),
        TeamPlayer("RB1", "RB", "BBB", fp_vor=40.0, cbs_vor=40.0),
        TeamPlayer("RB2", "RB", "CCC", fp_vor=30.0, cbs_vor=30.0),
    ]
    other_roster = [
        TeamPlayer("QB2", "QB", "DDD", fp_vor=45.0, cbs_vor=45.0),
        TeamPlayer("RB3", "RB", "EEE", fp_vor=35.0, cbs_vor=35.0),
        TeamPlayer("RB4", "RB", "FFF", fp_vor=25.0, cbs_vor=25.0),
    ]
    rosters = {"Me": my_roster, "Other": other_roster}
    assert find_trades("Me", rosters, STARTERS) == []


def test_trade_rejected_when_other_teams_cbs_gain_is_negative():
    # I have surplus + need lining up structurally, but CBS rates my
    # spare QB as nearly worthless while rating their spare RB (still
    # surplus -- 2 other RBs outrank it on their own roster) very highly
    # -- the other team's own (CBS-valued) side of the ledger comes out
    # negative, so they wouldn't perceive this as good for them and
    # nothing should be proposed, even though FantasyPoints alone would
    # call it a clear win for me.
    my_roster = [
        TeamPlayer("QB Starter", "QB", "AAA", fp_vor=50.0, cbs_vor=50.0),
        TeamPlayer("QB Spare", "QB", "BBB", fp_vor=10.0, cbs_vor=5.0),
        TeamPlayer("RB Starter", "RB", "CCC", fp_vor=-5.0, cbs_vor=-5.0),
    ]
    rival_roster = [
        TeamPlayer("Weak QB", "QB", "DDD", fp_vor=-10.0, cbs_vor=-10.0),
        TeamPlayer("RB1", "RB", "EEE", fp_vor=20.0, cbs_vor=200.0),
        TeamPlayer("RB2", "RB", "FFF", fp_vor=15.0, cbs_vor=150.0),
        TeamPlayer("RB Spare", "RB", "GGG", fp_vor=60.0, cbs_vor=100.0),
    ]
    rosters = {"Me": my_roster, "Rival": rival_roster}
    assert find_trades("Me", rosters, STARTERS) == []


def test_max_players_per_side_is_respected():
    my_roster = [
        TeamPlayer("QB Starter", "QB", "AAA", fp_vor=50.0, cbs_vor=50.0),
        TeamPlayer("QB Spare A", "QB", "BBB", fp_vor=10.0, cbs_vor=10.0),
        TeamPlayer("QB Spare B", "QB", "CCC", fp_vor=8.0, cbs_vor=8.0),
        TeamPlayer("QB Spare C", "QB", "DDD", fp_vor=6.0, cbs_vor=6.0),
        TeamPlayer("QB Spare D", "QB", "EEE", fp_vor=4.0, cbs_vor=4.0),
        TeamPlayer("RB Starter", "RB", "FFF", fp_vor=-5.0, cbs_vor=-5.0),
    ]
    rival_roster = [
        TeamPlayer("Weak QB", "QB", "GGG", fp_vor=-10.0, cbs_vor=-10.0),
        TeamPlayer("RB1", "RB", "HHH", fp_vor=20.0, cbs_vor=40.0),
        TeamPlayer("RB2", "RB", "III", fp_vor=15.0, cbs_vor=30.0),
        TeamPlayer("RB Spare", "RB", "JJJ", fp_vor=60.0, cbs_vor=5.0),
    ]
    rosters = {"Me": my_roster, "Rival": rival_roster}
    trades = find_trades("Me", rosters, STARTERS, max_players_per_side=3)
    assert trades
    assert len(trades[0].give) <= 3
    assert len(trades[0].get) <= 3


def test_trades_ranked_by_fp_gain_descending_across_teams():
    my_roster = [
        TeamPlayer("QB Starter", "QB", "AAA", fp_vor=50.0, cbs_vor=50.0),
        TeamPlayer("QB Spare", "QB", "BBB", fp_vor=10.0, cbs_vor=15.0),
        TeamPlayer("RB Starter", "RB", "CCC", fp_vor=-5.0, cbs_vor=-5.0),
    ]
    weak_rival = [
        TeamPlayer("Weak QB", "QB", "DDD", fp_vor=-10.0, cbs_vor=-10.0),
        TeamPlayer("RB1", "RB", "EEE", fp_vor=20.0, cbs_vor=40.0),
        TeamPlayer("RB2", "RB", "FFF", fp_vor=15.0, cbs_vor=30.0),
        TeamPlayer("RB Spare Small", "RB", "GGG", fp_vor=20.0, cbs_vor=5.0),
    ]
    generous_rival = [
        TeamPlayer("Weak QB 2", "QB", "HHH", fp_vor=-12.0, cbs_vor=-12.0),
        TeamPlayer("RB3", "RB", "III", fp_vor=22.0, cbs_vor=42.0),
        TeamPlayer("RB4", "RB", "JJJ", fp_vor=16.0, cbs_vor=32.0),
        TeamPlayer("RB Spare Big", "RB", "KKK", fp_vor=90.0, cbs_vor=6.0),
    ]
    rosters = {"Me": my_roster, "WeakRival": weak_rival, "GenerousRival": generous_rival}
    trades = find_trades("Me", rosters, STARTERS)
    assert [t.other_team for t in trades] == ["GenerousRival", "WeakRival"]
    assert trades[0].fp_gain_mine > trades[1].fp_gain_mine


def test_bye_week_note_flags_relief_when_incoming_player_breaks_a_cluster():
    my_roster = [
        TeamPlayer("QB Starter", "QB", "AAA", fp_vor=50.0, cbs_vor=50.0),
        TeamPlayer("QB Spare", "QB", "BBB", fp_vor=10.0, cbs_vor=15.0),
        TeamPlayer("RB Starter", "RB", "CCC", fp_vor=-5.0, cbs_vor=-5.0, bye_week=9),
        TeamPlayer("RB Bench", "RB", "DDD", fp_vor=-8.0, cbs_vor=-8.0, bye_week=9),
    ]
    rival_roster = [
        TeamPlayer("Weak QB", "QB", "EEE", fp_vor=-10.0, cbs_vor=-10.0),
        TeamPlayer("RB1", "RB", "FFF", fp_vor=20.0, cbs_vor=40.0),
        TeamPlayer("RB2", "RB", "GGG", fp_vor=15.0, cbs_vor=30.0),
        TeamPlayer("RB Spare", "RB", "HHH", fp_vor=60.0, cbs_vor=5.0, bye_week=4),
    ]
    rosters = {"Me": my_roster, "Rival": rival_roster}
    trades = find_trades("Me", rosters, STARTERS)
    assert len(trades) == 1
    assert trades[0].bye_note is not None
    assert "week 4" in trades[0].bye_note
    assert "week(s) 9" in trades[0].bye_note


def test_bye_week_note_absent_when_no_shared_bye_risk():
    my_roster = [
        TeamPlayer("QB Starter", "QB", "AAA", fp_vor=50.0, cbs_vor=50.0),
        TeamPlayer("QB Spare", "QB", "BBB", fp_vor=10.0, cbs_vor=15.0),
        TeamPlayer("RB Starter", "RB", "CCC", fp_vor=-5.0, cbs_vor=-5.0, bye_week=9),
    ]
    rival_roster = [
        TeamPlayer("Weak QB", "QB", "EEE", fp_vor=-10.0, cbs_vor=-10.0),
        TeamPlayer("RB1", "RB", "FFF", fp_vor=20.0, cbs_vor=40.0),
        TeamPlayer("RB2", "RB", "GGG", fp_vor=15.0, cbs_vor=30.0),
        TeamPlayer("RB Spare", "RB", "HHH", fp_vor=60.0, cbs_vor=5.0, bye_week=4),
    ]
    rosters = {"Me": my_roster, "Rival": rival_roster}
    trades = find_trades("Me", rosters, STARTERS)
    assert len(trades) == 1
    assert trades[0].bye_note is None


def test_dual_eligible_position_counts_for_either_slot():
    starters = [
        {"slot": "RB", "count": 1, "eligible": ["RB"]},
        {"slot": "TE", "count": 1, "eligible": ["TE"]},
    ]
    my_roster = [
        TeamPlayer("RB1", "RB", "AAA", fp_vor=-5.0, cbs_vor=-5.0),  # weak starter -> RB need
        TeamPlayer("TE Spare A", "TE", "BBB", fp_vor=5.0, cbs_vor=5.0),
        TeamPlayer("TE Spare B", "TE", "CCC", fp_vor=3.0, cbs_vor=3.0),  # surplus (only 1 TE slot)
    ]
    rival_roster = [
        TeamPlayer("Weak TE", "TE", "DDD", fp_vor=-3.0, cbs_vor=-3.0),  # weak starter -> TE need
        # Low cbs_vor keeps this behind "Weak TE" in the TE ranking (so it
        # doesn't itself claim the TE starter slot) and behind "RB2" in
        # the RB ranking -- surplus in BOTH position groups it's eligible
        # for, via dual eligibility.
        TeamPlayer("RB-TE Dual", "RB-TE", "EEE", fp_vor=50.0, cbs_vor=-5.0),
        TeamPlayer("RB2", "RB", "FFF", fp_vor=1.0, cbs_vor=50.0),
    ]
    rosters = {"Me": my_roster, "Rival": rival_roster}
    trades = find_trades("Me", rosters, starters)
    assert len(trades) == 1
    assert trades[0].get[0].name == "RB-TE Dual"


def test_empty_rosters_do_not_crash():
    assert find_trades("Me", {}, STARTERS) == []
    assert find_trades("Me", {"Me": []}, STARTERS) == []


def test_bench_only_add_is_not_proposed_as_a_fix():
    # League-manager feedback (2026-09-10): a "need" that's real on
    # paper (a below-replacement starter) shouldn't be filled by just
    # any surplus player if that player wouldn't actually crack the
    # starting lineup -- here I already roster 2 RBs (so RB isn't
    # numerically short), both below replacement, and the rival's
    # offered RB Spare is worse than BOTH of them under my own
    # (FantasyPoints) lens -- it would sit on my bench, not start, so
    # this shouldn't be proposed even though "RB is a need" is true.
    my_roster = [
        TeamPlayer("QB Starter", "QB", "AAA", fp_vor=50.0, cbs_vor=50.0),
        TeamPlayer("QB Spare", "QB", "BBB", fp_vor=10.0, cbs_vor=15.0),
        TeamPlayer("RB Starter", "RB", "CCC", fp_vor=-5.0, cbs_vor=-5.0),
        TeamPlayer("RB Bench", "RB", "DDD", fp_vor=-6.0, cbs_vor=-6.0),
    ]
    rival_roster = [
        TeamPlayer("Weak QB", "QB", "EEE", fp_vor=-10.0, cbs_vor=-10.0),
        TeamPlayer("RB1", "RB", "FFF", fp_vor=20.0, cbs_vor=40.0),
        TeamPlayer("RB2", "RB", "GGG", fp_vor=15.0, cbs_vor=30.0),
        TeamPlayer("RB Spare", "RB", "HHH", fp_vor=-7.0, cbs_vor=5.0),
    ]
    rosters = {"Me": my_roster, "Rival": rival_roster}
    assert find_trades("Me", rosters, STARTERS) == []


def test_true_upgrade_add_still_proposed_when_it_would_start():
    # Same shape as above, but this time the offered RB Spare actually
    # outvalues my weakest current RB starter under FantasyPoints, so
    # it would genuinely crack my starting lineup -- should still be
    # proposed.
    my_roster = [
        TeamPlayer("QB Starter", "QB", "AAA", fp_vor=50.0, cbs_vor=50.0),
        TeamPlayer("QB Spare", "QB", "BBB", fp_vor=10.0, cbs_vor=15.0),
        TeamPlayer("RB Starter", "RB", "CCC", fp_vor=-5.0, cbs_vor=-5.0),
        TeamPlayer("RB Bench", "RB", "DDD", fp_vor=-6.0, cbs_vor=-6.0),
    ]
    rival_roster = [
        TeamPlayer("Weak QB", "QB", "EEE", fp_vor=-10.0, cbs_vor=-10.0),
        TeamPlayer("RB1", "RB", "FFF", fp_vor=20.0, cbs_vor=40.0),
        TeamPlayer("RB2", "RB", "GGG", fp_vor=15.0, cbs_vor=30.0),
        TeamPlayer("RB Spare", "RB", "HHH", fp_vor=15.0, cbs_vor=5.0),
    ]
    rosters = {"Me": my_roster, "Rival": rival_roster}
    trades = find_trades("Me", rosters, STARTERS)
    assert len(trades) == 1
    assert [p.name for p in trades[0].get] == ["RB Spare"]


def test_totally_unrostered_position_still_counts_as_a_hole():
    # League-manager feedback (2026-09-10): "look at the holes in the
    # other teams roster that matches surpluses we have" -- a position
    # with ZERO rostered players (a dropped/streamed spot) must still
    # register as a need, not silently vanish for lack of any player to
    # rank. The rival here rosters no TE at all.
    starters = [
        {"slot": "QB", "count": 1, "eligible": ["QB"]},
        {"slot": "RB", "count": 2, "eligible": ["RB"]},
        {"slot": "TE", "count": 1, "eligible": ["TE"]},
    ]
    my_roster = [
        TeamPlayer("QB Starter", "QB", "AAA", fp_vor=50.0, cbs_vor=50.0),
        TeamPlayer("RB Starter", "RB", "BBB", fp_vor=-5.0, cbs_vor=-5.0),
        TeamPlayer("TE Starter", "TE", "CCC", fp_vor=10.0, cbs_vor=10.0),
        TeamPlayer("TE Spare", "TE", "DDD", fp_vor=3.0, cbs_vor=20.0),
    ]
    rival_roster = [
        TeamPlayer("Weak QB", "QB", "EEE", fp_vor=-10.0, cbs_vor=-10.0),
        TeamPlayer("RB1", "RB", "FFF", fp_vor=20.0, cbs_vor=40.0),
        TeamPlayer("RB2", "RB", "GGG", fp_vor=15.0, cbs_vor=30.0),
        TeamPlayer("RB Spare", "RB", "HHH", fp_vor=60.0, cbs_vor=5.0),
        # No TE at all on this roster.
    ]
    rosters = {"Me": my_roster, "Rival": rival_roster}
    trades = find_trades("Me", rosters, starters)
    assert len(trades) == 1
    assert [p.name for p in trades[0].give] == ["TE Spare"]
    assert [p.name for p in trades[0].get] == ["RB Spare"]
