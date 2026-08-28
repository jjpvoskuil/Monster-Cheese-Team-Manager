import os
import tempfile

import pytest
import yaml

from src.draft_state import DraftState, Pick
from src.roster_needs import (
    aggregate_opponent_demand,
    assign_roster_slots,
    opponent_needs_before_next_pick,
    positions_at_cap,
    positions_blocked_for_all,
    positions_that_would_fill,
    team_position_counts,
    unfilled_starter_slots,
)

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "league_settings.yaml",
)

TEAMS = [f"Team {i}" for i in range(1, 11)]
TEAMS[3] = "Monster Cheese"


def _fresh_state():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    return DraftState(teams=TEAMS, rounds=22, my_team="Monster Cheese", state_file=tmp.name)


def _real_starters():
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    return config, config["roster"]["starters"]


def test_team_position_counts_ignores_blank_positions():
    class FakePick:
        def __init__(self, position):
            self.position = position

    counts = team_position_counts([FakePick("QB"), FakePick("QB"), FakePick("RB"), FakePick("")])
    assert counts == {"QB": 2, "RB": 1}


def test_unfilled_starter_slots_fills_dedicated_slots_first():
    _, starters = _real_starters()
    # Drafted exactly enough for QB/RB/TE/K/DST dedicated slots, nothing
    # left over for the flex slots.
    counts = {"QB": 1, "RB": 3, "TE": 1, "K": 1, "DST": 1}
    unfilled = unfilled_starter_slots(counts, starters)
    # WR_TE_FLEX (needs 3, eligible WR/TE), SUPERFLEX (1, QB/RB/WR/TE),
    # FLEX (1, RB/WR/TE/K) should all still be fully unfilled -- nothing
    # left after the dedicated slots ate every drafted player.
    assert unfilled["WR_TE_FLEX"] == 3
    assert unfilled["SUPERFLEX"] == 1
    assert unfilled["FLEX"] == 1
    assert "QB" not in unfilled
    assert "RB" not in unfilled


def test_unfilled_starter_slots_extra_players_fill_flex_slots():
    _, starters = _real_starters()
    # A full legal-ish roster: dedicated slots plus enough extra
    # RB/WR/TE/QB/K to cover WR_TE_FLEX(3)/SUPERFLEX(1)/FLEX(1).
    counts = {"QB": 2, "RB": 4, "WR": 4, "TE": 2, "K": 1, "DST": 1}
    unfilled = unfilled_starter_slots(counts, starters)
    assert unfilled == {}


def test_positions_that_would_fill_spreads_demand_across_eligible_positions():
    _, starters = _real_starters()
    demand = positions_that_would_fill({"WR_TE_FLEX": 2}, starters)
    assert demand["WR"] == pytest.approx(1.0)
    assert demand["TE"] == pytest.approx(1.0)


def test_positions_that_would_fill_uses_flex_splits_when_given():
    config, starters = _real_starters()
    flex_splits = config["estimation_assumptions"]["flex_position_splits"]
    # Bug this fixes (SESSION_NOTES 2026-08-26): an unfilled SUPERFLEX
    # used to contribute an even 0.25 to QB, same as RB/WR/TE -- despite
    # this league's own modeling assumption (used elsewhere for VOR) that
    # SUPERFLEX is overwhelmingly likely to actually be started as a 2nd
    # QB (100% as of 2026-08-27 -- see league_settings.yaml's SUPERFLEX
    # comment). That made "need" nearly blind to a real, still-open
    # 2nd-QB requirement.
    demand = positions_that_would_fill({"SUPERFLEX": 1}, starters, flex_splits)
    assert demand["QB"] == pytest.approx(1.0)
    assert demand["RB"] == pytest.approx(0.0)
    assert demand["WR"] == pytest.approx(0.0)
    assert demand["TE"] == pytest.approx(0.0)


def test_positions_that_would_fill_flex_splits_still_sum_to_the_slots_need():
    config, starters = _real_starters()
    flex_splits = config["estimation_assumptions"]["flex_position_splits"]
    demand = positions_that_would_fill({"WR_TE_FLEX": 3, "FLEX": 2}, starters, flex_splits)
    # WR_TE_FLEX's 3 needed + FLEX's 2 needed = 5 total demand units,
    # regardless of how the weights carve it up across positions.
    assert sum(demand.values()) == pytest.approx(5.0)


def test_positions_that_would_fill_falls_back_to_even_split_for_uncovered_slot():
    _, starters = _real_starters()
    # flex_splits provided but doesn't mention this slot at all -- same
    # even-split behavior as passing no flex_splits.
    demand = positions_that_would_fill({"WR_TE_FLEX": 2}, starters, flex_splits={"SUPERFLEX": {"QB": 1.0}})
    assert demand["WR"] == pytest.approx(1.0)
    assert demand["TE"] == pytest.approx(1.0)


def test_opponent_needs_before_next_pick_covers_only_teams_ahead_of_me():
    config, starters = _real_starters()
    ds = _fresh_state()
    # Monster Cheese is picking 4th (TEAMS[3]); log 3 picks so it becomes
    # Monster Cheese's turn (picks_until_my_turn() == 0 -> no needs owed).
    for team in TEAMS[:3]:
        ds.log_pick(team, f"{team} Player", position="RB", nfl_team="XXX")
    assert ds.is_my_pick
    assert opponent_needs_before_next_pick(ds, config) == {}


def test_opponent_needs_before_next_pick_flags_teams_with_no_picks_yet():
    config, starters = _real_starters()
    ds = _fresh_state()
    # Nobody has picked yet; Monster Cheese is 4th, so 3 teams pick first,
    # each with a totally empty roster -> every slot unfilled -> QB/RB/WR
    # should show up with real demand for all 3 upcoming teams.
    needs = opponent_needs_before_next_pick(ds, config)
    assert set(needs.keys()) == set(TEAMS[:3])
    for team, demand in needs.items():
        assert demand["QB"] > 0
        assert demand["RB"] > 0

    total = aggregate_opponent_demand(needs)
    assert total["RB"] > 0
    assert total["QB"] > 0


# ---------------------------------------------------------------------
# positions_at_cap
# ---------------------------------------------------------------------

def test_positions_at_cap_flags_a_dedicated_position_at_its_configured_max():
    config, _ = _real_starters()
    limits = config["roster"]["position_active_limits"]
    at_cap_count = limits["RB"]["max"]
    capped = positions_at_cap({"RB": at_cap_count}, config)
    assert "RB" in capped


def test_positions_at_cap_leaves_a_position_below_its_max_uncapped():
    config, _ = _real_starters()
    limits = config["roster"]["position_active_limits"]
    below_cap = limits["RB"]["max"] - 1
    capped = positions_at_cap({"RB": below_cap}, config)
    assert "RB" not in capped


def test_positions_at_cap_wr_uses_the_combined_wr_te_bucket():
    config, _ = _real_starters()
    limits = config["roster"]["position_active_limits"]
    combined_max = limits["WR_TE"]["max"]
    # All WR, no TE -- still fills the combined bucket, so WR (and TE,
    # since they draw from the same bucket) both read as capped even
    # though this team has never drafted a TE.
    capped = positions_at_cap({"WR": combined_max, "TE": 0}, config)
    assert "WR" in capped
    assert "TE" in capped


def test_positions_at_cap_te_capped_by_its_own_max_even_below_the_combined_bucket():
    config, _ = _real_starters()
    limits = config["roster"]["position_active_limits"]
    te_max = limits["TE"]["max"]
    combined_max = limits["WR_TE"]["max"]
    assert te_max < combined_max  # sanity check on the real config's assumption this test relies on
    capped = positions_at_cap({"TE": te_max, "WR": 0}, config)
    assert "TE" in capped
    assert "WR" not in capped  # combined bucket still has room


def test_positions_at_cap_empty_roster_is_never_capped():
    config, _ = _real_starters()
    assert positions_at_cap({}, config) == set()


# ---------------------------------------------------------------------
# positions_blocked_for_all
# ---------------------------------------------------------------------

def test_positions_blocked_for_all_requires_every_window_team_capped():
    capped = {"Team A": {"RB", "TE"}, "Team B": {"RB"}}
    # RB: both teams capped -> blocked. TE: only Team A -> not blocked.
    assert positions_blocked_for_all(["Team A", "Team B"], capped) == {"RB"}


def test_positions_blocked_for_all_empty_window_is_never_blocked():
    capped = {"Team A": {"RB", "TE", "QB", "WR", "K", "DST"}}
    assert positions_blocked_for_all([], capped) == set()


def test_positions_blocked_for_all_a_team_missing_from_the_capped_map_blocks_nothing():
    # A team with no drafted picks yet (or simply absent from the map)
    # has no capped positions -- its presence in the window means
    # nothing can be "blocked for all" unless it's independently capped.
    capped = {"Team A": {"RB"}}
    assert positions_blocked_for_all(["Team A", "Team B"], capped) == set()


def test_positions_blocked_for_all_repeated_team_in_window_still_works():
    capped = {"Team A": {"RB"}}
    assert positions_blocked_for_all(["Team A", "Team A", "Team A"], capped) == {"RB"}


# ---------------------------------------------------------------------
# assign_roster_slots
# ---------------------------------------------------------------------

def _pick(overall_pick, name, position, nfl_team="XXX"):
    return Pick(
        overall_pick=overall_pick, round=overall_pick, pick_in_round=1,
        team="Monster Cheese", player_name=name, position=position, nfl_team=nfl_team,
    )


def test_assign_roster_slots_fills_dedicated_before_flex():
    _, starters = _real_starters()
    picks = [
        _pick(1, "QB1", "QB"),
        _pick(2, "RB1", "RB"),
        _pick(3, "RB2", "RB"),
        _pick(4, "RB3", "RB"),
    ]
    slots, bench = assign_roster_slots(picks, starters)
    assert [p.player_name if p else None for p in slots["QB"]] == ["QB1"]
    assert [p.player_name if p else None for p in slots["RB"]] == ["RB1", "RB2", "RB3"]
    # Dedicated slots ate everything -- flex slots still fully empty.
    assert slots["WR_TE_FLEX"] == [None, None, None]
    assert slots["SUPERFLEX"] == [None]
    assert bench == []


def test_assign_roster_slots_extra_players_fill_flex_then_bench():
    _, starters = _real_starters()
    picks = [
        _pick(1, "QB1", "QB"),
        _pick(2, "QB2", "QB"),  # 2nd QB -> SUPERFLEX
        _pick(3, "RB1", "RB"),
        _pick(4, "RB2", "RB"),
        _pick(5, "RB3", "RB"),
        _pick(6, "RB4", "RB"),  # 4th RB -> FLEX
        _pick(7, "WR1", "WR"),
        _pick(8, "TE1", "TE"),
        _pick(9, "K1", "K"),
        _pick(10, "DST1", "DST"),
        _pick(11, "RB5", "RB"),  # nothing left to fill -> bench
    ]
    slots, bench = assign_roster_slots(picks, starters)
    assert slots["QB"][0].player_name == "QB1"
    assert [p.player_name for p in slots["RB"]] == ["RB1", "RB2", "RB3"]
    assert slots["TE"][0].player_name == "TE1"  # dedicated TE slot is more restrictive, claims TE1 first
    assert slots["K"][0].player_name == "K1"
    assert slots["DST"][0].player_name == "DST1"
    # Only WR1 is left eligible for WR_TE_FLEX (TE1 already claimed above) --
    # fills 1 of 3 instances, the other 2 stay empty.
    assert [p.player_name if p else None for p in slots["WR_TE_FLEX"]] == ["WR1", None, None]
    assert slots["SUPERFLEX"][0].player_name == "QB2"  # 2nd QB spills into SUPERFLEX
    assert slots["FLEX"][0].player_name == "RB4"  # 4th RB spills into FLEX
    assert [p.player_name for p in bench] == ["RB5"]  # nothing left to fill -- bench


def test_assign_roster_slots_preserves_config_declared_order():
    _, starters = _real_starters()
    slots, _ = assign_roster_slots([], starters)
    assert list(slots.keys()) == [s["slot"] for s in starters]
    for slot in starters:
        assert slots[slot["slot"]] == [None] * slot["count"]


def test_assign_roster_slots_bench_is_leftover_in_draft_order():
    _, starters = _real_starters()
    # 3 Ks: dedicated K slot takes the 1st, FLEX (K-eligible) takes the
    # 2nd, and the 3rd has nowhere left to go -- true bench.
    picks = [_pick(1, "K1", "K"), _pick(2, "K2", "K"), _pick(3, "K3", "K")]
    slots, bench = assign_roster_slots(picks, starters)
    assert slots["K"][0].player_name == "K1"
    assert slots["FLEX"][0].player_name == "K2"
    assert [p.player_name for p in bench] == ["K3"]
