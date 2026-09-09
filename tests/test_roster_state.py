import os
import tempfile

import pandas as pd
import pytest

from src.draft_state import DraftState, Pick
from src.roster_state import current_roster_by_team, current_roster_for_team

TEAMS = ["Monster Cheese", "Team B", "Team C"]


def _fresh_state(picks: list[Pick]) -> DraftState:
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    state = DraftState(teams=TEAMS, rounds=3, my_team="Monster Cheese", state_file=tmp.name)
    state.picks = picks
    return state


def _pick(team, name, pos="RB", overall=1, nfl="XXX"):
    return Pick(overall_pick=overall, round=1, pick_in_round=overall, team=team,
                player_name=name, position=pos, nfl_team=nfl)


def _txn_df(rows: list[dict]) -> pd.DataFrame:
    defaults = dict(year=2026, txn_type=None, team=None, player_name=None,
                     position="RB", nfl_team="XXX", from_team=None,
                     effective_round=1, cost=0.0, action_text="")
    full_rows = []
    for r in rows:
        row = dict(defaults)
        row.update(r)
        full_rows.append(row)
    return pd.DataFrame(full_rows)


def test_no_transactions_matches_draft_roster_exactly():
    state = _fresh_state([_pick("Monster Cheese", "Player A", overall=1)])
    result = current_roster_by_team(state, pd.DataFrame())
    assert [p.player_name for p in result.rosters["Monster Cheese"]] == ["Player A"]
    assert result.warnings == []


def test_waiver_add_appends_new_player():
    state = _fresh_state([_pick("Monster Cheese", "Player A", overall=1)])
    txns = _txn_df([
        dict(date="2026-09-03T03:25:00", team="Monster Cheese", txn_type="waiver_add",
             player_name="Player B", position="WR"),
    ])
    result = current_roster_by_team(state, txns)
    names = [p.player_name for p in result.rosters["Monster Cheese"]]
    assert names == ["Player A", "Player B"]
    added = result.rosters["Monster Cheese"][1]
    assert added.round == 0  # signals "not from the draft"
    assert added.position == "WR"
    assert result.warnings == []


def test_drop_removes_player():
    state = _fresh_state([
        _pick("Monster Cheese", "Player A", overall=1),
        _pick("Monster Cheese", "Player B", overall=2),
    ])
    txns = _txn_df([
        dict(date="2026-09-03T03:25:00", team="Monster Cheese", txn_type="drop",
             player_name="Player A"),
    ])
    result = current_roster_by_team(state, txns)
    names = [p.player_name for p in result.rosters["Monster Cheese"]]
    assert names == ["Player B"]
    assert result.warnings == []


def test_drop_unknown_player_warns_without_crashing():
    state = _fresh_state([_pick("Monster Cheese", "Player A", overall=1)])
    txns = _txn_df([
        dict(date="2026-09-03T03:25:00", team="Monster Cheese", txn_type="drop",
             player_name="Nobody On This Roster"),
    ])
    result = current_roster_by_team(state, txns)
    assert [p.player_name for p in result.rosters["Monster Cheese"]] == ["Player A"]
    assert len(result.warnings) == 1
    assert "Nobody On This Roster" in result.warnings[0]


def test_trade_moves_player_between_teams():
    state = _fresh_state([
        _pick("Monster Cheese", "Player A", overall=1),
        _pick("Team B", "Player X", overall=2),
    ])
    txns = _txn_df([
        dict(date="2026-09-02T11:00:00", team="Team B", txn_type="trade_in",
             player_name="Player A", from_team="Monster Cheese"),
        dict(date="2026-09-02T11:00:00", team="Monster Cheese", txn_type="trade_in",
             player_name="Player X", from_team="Team B"),
    ])
    result = current_roster_by_team(state, txns)
    mc_names = sorted(p.player_name for p in result.rosters["Monster Cheese"])
    tb_names = sorted(p.player_name for p in result.rosters["Team B"])
    assert mc_names == ["Player X"]
    assert tb_names == ["Player A"]
    assert result.warnings == []


def test_trade_from_unknown_team_warns_but_still_adds():
    state = _fresh_state([_pick("Monster Cheese", "Player A", overall=1)])
    txns = _txn_df([
        dict(date="2026-09-02T11:00:00", team="Monster Cheese", txn_type="trade_in",
             player_name="Player Z", from_team="Some Other League's Team"),
    ])
    result = current_roster_by_team(state, txns)
    names = [p.player_name for p in result.rosters["Monster Cheese"]]
    assert "Player Z" in names
    assert len(result.warnings) == 1


def test_unrecognized_txn_type_skipped_with_warning():
    state = _fresh_state([_pick("Monster Cheese", "Player A", overall=1)])
    txns = _txn_df([
        dict(date="2026-09-03T03:25:00", team="Monster Cheese", txn_type="other",
             player_name="Player B", action_text="Something new CBS added"),
    ])
    result = current_roster_by_team(state, txns)
    assert [p.player_name for p in result.rosters["Monster Cheese"]] == ["Player A"]
    assert len(result.warnings) == 1


def test_transaction_for_unknown_team_skipped_with_warning():
    state = _fresh_state([_pick("Monster Cheese", "Player A", overall=1)])
    txns = _txn_df([
        dict(date="2026-09-03T03:25:00", team="Not A Real Team", txn_type="waiver_add",
             player_name="Player B"),
    ])
    result = current_roster_by_team(state, txns)
    assert [p.player_name for p in result.rosters["Monster Cheese"]] == ["Player A"]
    assert len(result.warnings) == 1


def test_re_add_after_drop_then_add_again_ends_up_present():
    """A player dropped and later re-added (by the same or another team)
    should end up correctly present -- regression against an earlier
    draft of this logic that only ever appended and never checked for
    an existing entry before re-adding."""
    state = _fresh_state([_pick("Monster Cheese", "Player A", overall=1)])
    txns = _txn_df([
        dict(date="2026-09-01T00:00:00", team="Monster Cheese", txn_type="drop",
             player_name="Player A"),
        dict(date="2026-09-02T00:00:00", team="Monster Cheese", txn_type="waiver_add",
             player_name="Player A"),
    ])
    result = current_roster_by_team(state, txns)
    names = [p.player_name for p in result.rosters["Monster Cheese"]]
    assert names.count("Player A") == 1


def test_current_roster_for_team_narrows_to_one_team_but_still_resolves_trades():
    state = _fresh_state([
        _pick("Monster Cheese", "Player A", overall=1),
        _pick("Team B", "Player X", overall=2),
    ])
    txns = _txn_df([
        dict(date="2026-09-02T11:00:00", team="Monster Cheese", txn_type="trade_in",
             player_name="Player X", from_team="Team B"),
    ])
    result = current_roster_for_team(state, txns, "Monster Cheese")
    assert set(result.rosters.keys()) == {"Monster Cheese"}
    assert "Player X" in [p.player_name for p in result.rosters["Monster Cheese"]]


def test_real_2026_data_end_to_end():
    """Sanity check against the real captured 2026 transaction data,
    layered on a minimal synthetic draft covering the teams involved."""
    from src.data_sources.transactions import load_transactions

    csv_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "transactions", "transactions.csv",
    )
    if not os.path.exists(csv_path):
        pytest.skip("data/transactions/transactions.csv not generated yet")

    real_teams = ["Monster Cheese", "THE DEMONS", "Buckhorns", "Ball Busters",
                  "Aces High", "Legion of Doom", "Mojo", "Salty Dogs"]
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    state = DraftState(teams=real_teams, rounds=1, my_team="Monster Cheese", state_file=tmp.name)
    # Give Ball Busters and THE DEMONS a player each so the drop/trade
    # rows have something real to remove.
    state.picks = [
        _pick("Ball Busters", "Adam Randall", overall=1),
        # Pre-trade ownership: THE DEMONS held Packers DST, Buckhorns held
        # Fernando Mendoza -- each row's "Traded from X" names where the
        # player came FROM, so X is who originally had it.
        _pick("THE DEMONS", "Packers", overall=2, pos="DST"),
        _pick("Buckhorns", "Fernando Mendoza", overall=3, pos="QB"),
    ]
    txns = load_transactions(csv_path)
    result = current_roster_by_team(state, txns)

    mc_names = [p.player_name for p in result.rosters["Monster Cheese"]]
    assert mc_names == ["Samaje Perine"]

    bb_names = [p.player_name for p in result.rosters["Ball Busters"]]
    assert "Adam Randall" not in bb_names  # dropped
    assert "Andy Dalton" in bb_names  # added

    demons_names = [p.player_name for p in result.rosters["THE DEMONS"]]
    assert "Packers" not in demons_names  # traded away
    assert "Fernando Mendoza" in demons_names  # traded in
    assert "Christopher Brooks" in demons_names  # waiver add

    buckhorns_names = [p.player_name for p in result.rosters["Buckhorns"]]
    assert "Fernando Mendoza" not in buckhorns_names  # traded away
    assert "Packers" in buckhorns_names  # traded in
