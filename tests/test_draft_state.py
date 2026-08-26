import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.draft_state import DraftState  # noqa: E402

TEAMS = [f"Team {i}" for i in range(1, 11)]
TEAMS[3] = "Monster Cheese"


def _fresh_state():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)  # start from no file
    return DraftState(teams=TEAMS, rounds=22, my_team="Monster Cheese", state_file=tmp.name)


def test_snake_order_round_1_and_2():
    ds = _fresh_state()
    assert ds.team_for_pick(1) == TEAMS[0]
    assert ds.team_for_pick(10) == TEAMS[9]
    # round 2 reverses
    assert ds.team_for_pick(11) == TEAMS[9]
    assert ds.team_for_pick(20) == TEAMS[0]


def test_log_and_undo_pick():
    ds = _fresh_state()
    p = ds.log_pick_on_the_clock("Justin Jefferson", position="WR", nfl_team="MIN")
    assert p.overall_pick == 1
    assert ds.next_overall_pick == 2
    undone = ds.undo_last_pick()
    assert undone.player_name == "Justin Jefferson"
    assert ds.next_overall_pick == 1


def test_is_my_pick():
    ds = _fresh_state()
    # Monster Cheese is 4th team (index 3), so picks 1-3 aren't mine
    assert not ds.is_my_pick
    for _ in range(3):
        ds.log_pick_on_the_clock(f"Filler {ds.next_overall_pick}")
    assert ds.is_my_pick
    assert ds.picks_until_my_turn() == 0


def test_upcoming_picks_returns_next_n_with_correct_teams():
    ds = _fresh_state()
    upcoming = ds.upcoming_picks(3)
    assert [u["overall_pick"] for u in upcoming] == [1, 2, 3]
    assert [u["team"] for u in upcoming] == [TEAMS[0], TEAMS[1], TEAMS[2]]
    assert upcoming[0]["round"] == 1 and upcoming[0]["pick_in_round"] == 1


def test_upcoming_picks_advances_as_picks_are_logged():
    ds = _fresh_state()
    ds.log_pick_on_the_clock("Filler 1")
    upcoming = ds.upcoming_picks(2)
    assert [u["overall_pick"] for u in upcoming] == [2, 3]


def test_upcoming_picks_caps_at_total_picks_near_draft_end():
    ds = _fresh_state()
    ds.rounds = 1  # 10 total picks
    for _ in range(8):
        ds.log_pick_on_the_clock(f"Filler {ds.next_overall_pick}")
    upcoming = ds.upcoming_picks(10)
    assert len(upcoming) == 2
    assert [u["overall_pick"] for u in upcoming] == [9, 10]


def test_upcoming_picks_empty_when_draft_complete():
    ds = _fresh_state()
    ds.rounds = 1
    for _ in range(10):
        ds.log_pick_on_the_clock(f"Filler {ds.next_overall_pick}")
    assert ds.is_draft_complete
    assert ds.upcoming_picks(10) == []


def test_persistence_round_trip():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)  # start from no file, same as _fresh_state()
    ds1 = DraftState(teams=TEAMS, rounds=22, my_team="Monster Cheese", state_file=tmp.name)
    ds1.log_pick_on_the_clock("Test Player", position="RB")
    ds2 = DraftState(teams=TEAMS, rounds=22, my_team="Monster Cheese", state_file=tmp.name)
    assert len(ds2.picks) == 1
    assert ds2.picks[0].player_name == "Test Player"
    os.unlink(tmp.name)
