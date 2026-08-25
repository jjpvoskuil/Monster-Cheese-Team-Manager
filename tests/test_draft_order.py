import os
import tempfile

import pytest

from src.data_sources.draft_order import parse_draft_order_text, draft_results_url
from src.draft_state import DraftState

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "draft", "2026_draft_order_raw.txt",
)

ROUND1 = [
    "Mississippi Swamp Ass", "Aces High", "THE DEMONS", "Pimp Daddy",
    "Legion of Doom", "Mojo", "Salty Dogs", "Monster Cheese",
    "Buckhorns", "Ball Busters",
]


def test_parses_real_2026_capture():
    with open(FIXTURE_PATH) as f:
        text = f.read()
    result = parse_draft_order_text(text)
    assert result.rounds == 22
    assert result.teams_per_round == 10
    assert result.team_order == ROUND1
    assert result.is_standard_snake is True
    assert result.notes == []
    # Round 2 must be the exact reverse of round 1 (standard snake).
    assert result.round_orders[1] == list(reversed(ROUND1))
    # Round 3 must match round 1 again.
    assert result.round_orders[2] == ROUND1


def test_minimal_two_round_snake():
    text = """
ROUND 1
PICK TEAM PLAYER
1 Alpha
2 Beta
3 Gamma
ROUND 2
PICK TEAM PLAYER
1 Gamma
2 Beta
3 Alpha
"""
    result = parse_draft_order_text(text)
    assert result.team_order == ["Alpha", "Beta", "Gamma"]
    assert result.is_standard_snake is True
    assert result.rounds == 2
    assert result.teams_per_round == 3


def test_non_standard_order_flagged_not_raised():
    text = """
ROUND 1
PICK TEAM PLAYER
1 Alpha
2 Beta
3 Gamma
ROUND 2
PICK TEAM PLAYER
1 Alpha
2 Gamma
3 Beta
"""
    result = parse_draft_order_text(text)
    assert result.is_standard_snake is False
    assert result.notes  # explains why DraftState's snake assumption won't hold


def test_no_rounds_found_raises():
    with pytest.raises(ValueError):
        parse_draft_order_text("nothing relevant here")


def test_inconsistent_pick_counts_raise():
    text = """
ROUND 1
PICK TEAM PLAYER
1 Alpha
2 Beta
ROUND 2
PICK TEAM PLAYER
1 Beta
2 Alpha
3 Gamma
"""
    with pytest.raises(ValueError):
        parse_draft_order_text(text)


def test_duplicate_team_in_round_raises():
    text = """
ROUND 1
PICK TEAM PLAYER
1 Alpha
2 Alpha
"""
    with pytest.raises(ValueError):
        parse_draft_order_text(text)


def test_draft_results_url_matches_known_good_2026_url():
    assert draft_results_url(2026) == (
        "https://maniacfl.football.cbssports.com/draft/results/"
        "2026:Pre-season:MFL%20Draft%202026/"
    )


def test_draft_results_url_generalizes_to_other_years():
    assert "2030" in draft_results_url(2030)
    assert draft_results_url(2030).endswith("2030:Pre-season:MFL%20Draft%202030/")


def test_parsed_team_order_feeds_draft_state_correctly():
    """The whole point of this feature: the parsed round-1 order should
    make DraftState compute the same team-on-the-clock CBS shows for
    every pick, for every round — not just round 1."""
    with open(FIXTURE_PATH) as f:
        text = f.read()
    result = parse_draft_order_text(text)

    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)  # start from no file, matching tests/test_draft_state.py's pattern
    try:
        state = DraftState(
            teams=result.team_order, rounds=result.rounds, my_team="Monster Cheese",
            state_file=tmp.name,
        )

        for round_idx, expected_order in enumerate(result.round_orders, start=1):
            for pick_in_round, expected_team in enumerate(expected_order, start=1):
                overall = (round_idx - 1) * result.teams_per_round + pick_in_round
                assert state.team_for_pick(overall) == expected_team, (
                    f"round {round_idx} pick {pick_in_round} (overall {overall})"
                )

        # Monster Cheese drafts 8th overall in round 1.
        assert state.team_for_pick(8) == "Monster Cheese"
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
