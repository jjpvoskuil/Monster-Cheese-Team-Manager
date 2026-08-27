from src.lineup_value import LineupPlayer, expand_slots, optimal_lineup_points

STARTERS = [
    {"slot": "QB", "count": 1, "eligible": ["QB"]},
    {"slot": "RB", "count": 2, "eligible": ["RB"]},
    {"slot": "FLEX", "count": 1, "eligible": ["RB", "WR", "TE"]},
]


def test_expand_slots_counts():
    expanded = expand_slots(STARTERS)
    assert len(expanded) == 4
    assert [s["slot"] for s in expanded] == ["QB", "RB", "RB", "FLEX"]


def test_optimal_lineup_picks_best_eligible_not_draft_order():
    # FLEX should grab the best remaining RB/WR/TE by points, regardless
    # of which order these were "drafted" in the input list.
    players = [
        LineupPlayer("QB1", "QB", 300.0),
        LineupPlayer("RB1", "RB", 200.0),
        LineupPlayer("RB2", "RB", 150.0),
        LineupPlayer("RB3", "RB", 140.0),  # best remaining RB -> should fill FLEX
        LineupPlayer("WR1", "WR", 100.0),
    ]
    total = optimal_lineup_points(players, STARTERS)
    # QB1 (300) + RB1 (200) + RB2 (150) + RB3 in FLEX (140) = 790, beating
    # a draft-order greedy fill that would give FLEX to WR1 (100) instead.
    assert total == 790.0


def test_empty_slot_scores_zero_not_forced_illegal():
    # No kicker anywhere in the pool -- a K slot should just contribute 0,
    # not force some other position into it.
    starters = [{"slot": "K", "count": 1, "eligible": ["K"]}]
    players = [LineupPlayer("QB1", "QB", 300.0)]
    assert optimal_lineup_points(players, starters) == 0.0


def test_no_players_or_no_slots():
    assert optimal_lineup_points([], STARTERS) == 0.0
    assert optimal_lineup_points([LineupPlayer("QB1", "QB", 10.0)], []) == 0.0


def test_pads_when_fewer_players_than_slots():
    starters = [{"slot": "RB", "count": 3, "eligible": ["RB"]}]
    players = [LineupPlayer("RB1", "RB", 100.0), LineupPlayer("RB2", "RB", 80.0)]
    # Only 2 real RBs for 3 slots -- 3rd slot stays empty (0), not an error.
    assert optimal_lineup_points(players, starters) == 180.0
