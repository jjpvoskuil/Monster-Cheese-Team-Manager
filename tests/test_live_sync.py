import os
import tempfile

from src.draft_state import DraftState
from src.live_sync import (
    LivePick,
    parse_live_room_dump,
    parse_live_room_player_cell,
    parse_player_cell,
    read_sync_status,
    sync_new_picks,
    write_sync_status,
)

TEAMS = [f"Team {i}" for i in range(1, 11)]
TEAMS[3] = "Monster Cheese"


def _fresh_state():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    return DraftState(teams=TEAMS, rounds=3, my_team="Monster Cheese", state_file=tmp.name)


def test_parse_player_cell_matches_historical_format():
    assert parse_player_cell("Josh Allen QB • BUF") == ("Josh Allen", "QB", "BUF")
    assert parse_player_cell("Ezekiel Elliott RB •") == ("Ezekiel Elliott", "RB", "")
    assert parse_player_cell("*Austin Hooper TE • ATL") == ("Austin Hooper", "TE", "ATL")
    assert parse_player_cell("Taysom Hill QB,TE • NO") == ("Taysom Hill", "QB", "NO")
    assert parse_player_cell("Eagles DST • PHI") == ("Eagles", "DST", "PHI")


def test_sync_logs_picks_starting_from_the_current_draft_state():
    ds = _fresh_state()
    live = [
        LivePick(1, TEAMS[0], "Josh Allen", "QB", "BUF"),
        LivePick(2, TEAMS[1], "Derrick Henry", "RB", "BAL"),
    ]
    result = sync_new_picks(ds, live)
    assert len(result.newly_logged) == 2
    assert result.already_known == 0
    assert not result.has_mismatch
    assert ds.next_overall_pick == 3
    assert [p.player_name for p in ds.picks] == ["Josh Allen", "Derrick Henry"]


def test_sync_only_applies_contiguous_picks_and_reports_the_gap():
    ds = _fresh_state()
    # pick #2 is present but #1 is missing from this extraction (e.g. a
    # flaky poll that only caught part of the panel) -- must NOT log #2
    # out of order.
    live = [LivePick(2, TEAMS[1], "Derrick Henry", "RB", "BAL")]
    result = sync_new_picks(ds, live)
    assert result.newly_logged == []
    assert ds.next_overall_pick == 1
    assert result.pending_ahead == [f"#2 {TEAMS[1]}: Derrick Henry"]


def test_sync_is_idempotent_on_repeated_polls():
    ds = _fresh_state()
    live = [LivePick(1, TEAMS[0], "Josh Allen", "QB", "BUF")]
    first = sync_new_picks(ds, live)
    assert len(first.newly_logged) == 1

    # simulate a second poll of the same (now-stale) extraction
    second = sync_new_picks(ds, live)
    assert second.newly_logged == []
    assert second.already_known == 1
    assert not second.has_mismatch


def test_sync_flags_a_genuine_mismatch_instead_of_silently_overwriting():
    ds = _fresh_state()
    ds.log_pick(TEAMS[0], "Josh Allen", position="QB", nfl_team="BUF")

    # a later poll's extraction disagrees with what's already logged for
    # pick #1 -- e.g. a parsing glitch, or picks arriving out of order.
    live = [LivePick(1, TEAMS[0], "Patrick Mahomes", "QB", "KC")]
    result = sync_new_picks(ds, live)
    assert result.newly_logged == []
    assert result.has_mismatch
    assert "Josh Allen" in result.mismatches[0]
    assert "Patrick Mahomes" in result.mismatches[0]
    # the already-logged pick is untouched
    assert ds.picks[0].player_name == "Josh Allen"


def test_sync_advances_across_multiple_polls_as_new_picks_appear():
    ds = _fresh_state()
    r1 = sync_new_picks(ds, [LivePick(1, TEAMS[0], "Josh Allen", "QB", "BUF")])
    assert len(r1.newly_logged) == 1

    # next poll's extraction includes pick 1 again (already known) plus
    # the newly-made pick 2
    r2 = sync_new_picks(ds, [
        LivePick(1, TEAMS[0], "Josh Allen", "QB", "BUF"),
        LivePick(2, TEAMS[1], "Derrick Henry", "RB", "BAL"),
    ])
    assert [p.player_name for p in r2.newly_logged] == ["Derrick Henry"]
    assert r2.already_known == 1
    assert ds.next_overall_pick == 3


def test_sync_stops_at_draft_complete_without_erroring():
    ds = _fresh_state()  # 3 rounds x 10 teams = 30 picks
    live = [
        LivePick(i, TEAMS[(i - 1) % 10], f"Player{i}", "RB", "XXX")
        for i in range(1, 31)
    ]
    result = sync_new_picks(ds, live)
    assert len(result.newly_logged) == 30
    assert ds.is_draft_complete

    # polling again after the draft is complete must not error or re-log
    result2 = sync_new_picks(ds, live)
    assert result2.newly_logged == []


def test_write_and_read_sync_status_round_trips():
    ds = _fresh_state()
    result = sync_new_picks(ds, [LivePick(1, TEAMS[0], "Josh Allen", "QB", "BUF")])

    with tempfile.TemporaryDirectory() as d:
        status_path = os.path.join(d, "live_sync_status.json")
        assert read_sync_status(status_path) is None  # nothing written yet

        write_sync_status(status_path, ds, result)
        status = read_sync_status(status_path)
        assert status["last_synced_overall_pick"] == 1
        assert status["newly_logged_this_pass"] == ["Josh Allen"]
        assert status["mismatches"] == []
        assert "last_sync_at" in status


def test_read_sync_status_survives_a_corrupt_file():
    with tempfile.TemporaryDirectory() as d:
        status_path = os.path.join(d, "live_sync_status.json")
        with open(status_path, "w") as f:
            f.write("{not valid json")
        assert read_sync_status(status_path) is None


# ---------------------------------------------------------------------
# Live draft room ("Last, First (POS TEAM)") parsing -- these fixtures
# are the ACTUAL text captured 2026-08-25 by joining a real CBS mock
# draft and dumping its #DraftRoom.views.results panel, not synthetic
# data, so this is a real regression test against CBS's live format.
# ---------------------------------------------------------------------

REAL_LIVE_ROOM_DUMP = """\
1|5|bulldogs|McCaffrey, Christian (RB SF)
1|4|NWA|Nacua, Puka (WR LAR)
1|3|IC Champs|Taylor, Jonathan (RB IND)
1|2|Specks|Robinson, Bijan (RB ATL)
1|1|Paulie Walnuts|Gibbs, Jahmyr (RB DET)
"""

# Fuller capture a few minutes into the same real mock draft: 2 rounds,
# including autopilot ("*"-prefixed) picks, a team name with a space
# ("Auto-Pilot Team 7" -- the slot nobody claimed, auto-filled by CBS),
# and a last name containing its own comma-adjacent punctuation
# ("St. Brown, Amon-Ra" -- must NOT get mis-split into "St." / "Brown").
REAL_LIVE_ROOM_DUMP_ROUND_2 = """\
2|14|Auto-Pilot Team 7|*St. Brown, Amon-Ra (WR DET)
2|13|MZ|Barkley, Saquon (RB PHI)
2|12|7th|Cook, James (RB BUF)
2|11|MC Sync Test|*Henry, Derrick (RB BAL)
1|10|MC Sync Test|*London, Drake (WR ATL)
1|9|7th|Chase, Ja'Marr (WR CIN)
1|8|MZ|Brown, Chase (RB CIN)
1|7|Auto-Pilot Team 7|*Achane, De'Von (RB MIA)
1|6|butch|Smith-Njigba, Jaxon (WR SEA)
1|5|bulldogs|McCaffrey, Christian (RB SF)
1|4|NWA|Nacua, Puka (WR LAR)
1|3|IC Champs|Taylor, Jonathan (RB IND)
1|2|Specks|Robinson, Bijan (RB ATL)
1|1|Paulie Walnuts|Gibbs, Jahmyr (RB DET)
"""


def test_parse_live_room_player_cell_basic():
    assert parse_live_room_player_cell("Nacua, Puka (WR LAR)") == ("Puka Nacua", "WR", "LAR")
    assert parse_live_room_player_cell("Gibbs, Jahmyr (RB DET)") == ("Jahmyr Gibbs", "RB", "DET")


def test_parse_live_room_player_cell_handles_suffix_in_last_name():
    # "Walker III, Kenneth (RB KC)" -- the suffix stays attached to the
    # last name on CBS's side of the comma, so the reassembled name
    # should read naturally as "Kenneth Walker III".
    assert parse_live_room_player_cell("Walker III, Kenneth (RB KC)") == ("Kenneth Walker III", "RB", "KC")


def test_parse_live_room_player_cell_strips_autopilot_asterisk():
    # Real captured case: a pick made by a team's autopilot (or an empty
    # slot CBS fills itself) is prefixed with "*", same as the
    # historical results page's convention.
    assert parse_live_room_player_cell("*Henry, Derrick (RB BAL)") == ("Derrick Henry", "RB", "BAL")
    assert parse_live_room_player_cell("*London, Drake (WR ATL)") == ("Drake London", "WR", "ATL")


def test_parse_live_room_player_cell_no_comma_falls_back_to_whole_name():
    # DST / edge-case cells without a "Last, First" comma
    assert parse_live_room_player_cell("Eagles (DST PHI)") == ("Eagles", "DST", "PHI")


def test_parse_live_room_player_cell_unrecognized_shape_does_not_crash():
    name, pos, team = parse_live_room_player_cell("???totally unexpected???")
    assert name == "???totally unexpected???"
    assert pos == ""
    assert team == ""


def test_parse_live_room_dump_uses_the_pick_column_as_overall_pick_directly():
    picks = parse_live_room_dump(REAL_LIVE_ROOM_DUMP)
    by_overall = {p.overall_pick: p for p in picks}
    assert len(picks) == 5
    assert by_overall[1] == LivePick(1, "Paulie Walnuts", "Jahmyr Gibbs", "RB", "DET")
    assert by_overall[2] == LivePick(2, "Specks", "Bijan Robinson", "RB", "ATL")
    assert by_overall[5] == LivePick(5, "bulldogs", "Christian McCaffrey", "RB", "SF")


def test_parse_live_room_dump_round_2_pick_column_already_continues_the_count():
    # Confirmed against real CBS data: unlike the historical results
    # page, the live room's "Pick" column does NOT reset to 1 at the
    # start of round 2 -- it keeps counting up (11, 12, 13...). The
    # round field must NOT be used to recompute an offset.
    dump = "2|11|Team A|Gibbs, Jahmyr (RB DET)\n2|13|Team B|Nacua, Puka (WR LAR)\n"
    picks = parse_live_room_dump(dump)
    overalls = sorted(p.overall_pick for p in picks)
    assert overalls == [11, 13]


def test_real_live_room_dump_feeds_end_to_end_into_draft_state():
    """The real captured dump, run all the way through parse ->
    sync_new_picks -> DraftState, matching the exact live-draft-room
    team names and pick order observed (descending within the round)."""
    teams = ["Paulie Walnuts", "Specks", "IC Champs", "NWA", "bulldogs",
             "butch", "Team7", "MZ", "Team9", "MC Sync Test"]
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    ds = DraftState(teams=teams, rounds=14, my_team="MC Sync Test", state_file=tmp.name)

    live_picks = parse_live_room_dump(REAL_LIVE_ROOM_DUMP)
    result = sync_new_picks(ds, live_picks)

    assert len(result.newly_logged) == 5
    assert not result.has_mismatch
    assert ds.next_overall_pick == 6
    assert [p.player_name for p in ds.picks] == [
        "Jahmyr Gibbs", "Bijan Robinson", "Jonathan Taylor", "Puka Nacua", "Christian McCaffrey",
    ]
    assert [p.team for p in ds.picks] == [
        "Paulie Walnuts", "Specks", "IC Champs", "NWA", "bulldogs",
    ]


def test_real_live_room_round_2_dump_handles_autopilot_and_punctuated_names():
    teams = ["Paulie Walnuts", "Specks", "IC Champs", "NWA", "bulldogs",
             "butch", "Auto-Pilot Team 7", "MZ", "7th", "MC Sync Test"]
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    ds = DraftState(teams=teams, rounds=14, my_team="MC Sync Test", state_file=tmp.name)

    live_picks = parse_live_room_dump(REAL_LIVE_ROOM_DUMP_ROUND_2)
    result = sync_new_picks(ds, live_picks)

    assert len(result.newly_logged) == 14
    assert not result.has_mismatch
    assert ds.next_overall_pick == 15
    # picks 10 and 11 are MC Sync Test's own autopilot picks -- the "*"
    # must be stripped, not baked into the player name
    pick10, pick11 = ds.picks[9], ds.picks[10]
    assert pick10.player_name == "Drake London" and pick10.team == "MC Sync Test"
    assert pick11.player_name == "Derrick Henry" and pick11.team == "MC Sync Test"
    # "St. Brown, Amon-Ra" must reassemble correctly despite the extra period
    pick14 = ds.picks[13]
    assert pick14.player_name == "Amon-Ra St. Brown"
    assert pick14.team == "Auto-Pilot Team 7"
