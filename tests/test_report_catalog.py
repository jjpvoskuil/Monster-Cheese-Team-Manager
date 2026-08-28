import pandas as pd
import pytest

from src.draft_state import DraftState, Pick
from src.report_catalog import (
    REPORTS,
    ReportContext,
    available_players_report,
    build_workbook_sheets,
    league_rosters_report,
    my_roster_bench_report,
    my_roster_lineup_report,
    opponent_needs_report,
    pick_log_report,
    safe_sheet_name,
)

STARTERS = [
    {"slot": "QB", "count": 1, "eligible": ["QB"]},
    {"slot": "RB", "count": 2, "eligible": ["RB"]},
    {"slot": "FLEX", "count": 1, "eligible": ["RB", "WR", "TE"]},
]
CONFIG = {
    "league": {"team_name": "Team A", "teams": 2},
    "roster": {"starters": STARTERS},
    "estimation_assumptions": {},
}
TEAMS = ["Team A", "Team B"]


def _draft_state(state_file):
    return DraftState(teams=TEAMS, rounds=3, my_team="Team A", state_file=state_file)


def _players_df():
    return pd.DataFrame([
        {"name": "QB One", "position": "QB", "nfl_team": "AAA", "score_total": 300.0,
         "vor": 50.0, "tier": 1, "vor_rank": 1, "overall_rank": 1, "position_rank": 1},
        {"name": "RB One", "position": "RB", "nfl_team": "BBB", "score_total": 200.0,
         "vor": 40.0, "tier": 1, "vor_rank": 2, "overall_rank": 2, "position_rank": 1},
    ])


def _ctx(tmp_path, picks_a=(), picks_b=()):
    state_file = str(tmp_path / "draft_state.json")
    ds = _draft_state(state_file)
    for p in picks_a:
        ds.log_pick(team="Team A", player_name=p[0], position=p[1])
    for p in picks_b:
        ds.log_pick(team="Team B", player_name=p[0], position=p[1])
    players_df = _players_df()
    return ReportContext(
        config=CONFIG, draft_state=ds, teams=TEAMS, my_team="Team A",
        players_df=players_df, points_by_name=players_df.set_index("name")["score_total"],
    )


def test_safe_sheet_name_strips_illegal_characters_and_truncates():
    taken = set()
    name = safe_sheet_name("Team: A/B [Test]?*", taken)
    assert not any(c in name for c in ":\\/?*[]")
    assert len(name) <= 31


def test_safe_sheet_name_deduplicates():
    taken = set()
    a = safe_sheet_name("Same Name", taken)
    b = safe_sheet_name("Same Name", taken)
    assert a != b
    assert a in taken and b in taken


def test_safe_sheet_name_truncates_a_very_long_name_and_still_dedupes():
    taken = set()
    long_name = "X" * 50
    a = safe_sheet_name(long_name, taken)
    b = safe_sheet_name(long_name, taken)
    assert len(a) <= 31 and len(b) <= 31
    assert a != b


def test_available_players_report_excludes_drafted_players(tmp_path):
    ctx = _ctx(tmp_path, picks_a=[("QB One", "QB")])
    df = available_players_report(ctx)
    assert "QB One" not in df["Player"].values
    assert "RB One" in df["Player"].values


def test_pick_log_report_lists_every_pick_in_order(tmp_path):
    ctx = _ctx(tmp_path, picks_a=[("QB One", "QB")], picks_b=[("RB One", "RB")])
    df = pick_log_report(ctx)
    assert list(df["Player"]) == ["QB One", "RB One"]
    assert list(df["Team"]) == ["Team A", "Team B"]


def test_pick_log_report_empty_when_nothing_drafted(tmp_path):
    ctx = _ctx(tmp_path)
    df = pick_log_report(ctx)
    assert df.empty
    assert list(df.columns) == ["Pick", "Rd", "Team", "Player", "Pos", "NFL Team"]


def test_my_roster_lineup_report_shows_my_team_only(tmp_path):
    ctx = _ctx(tmp_path, picks_a=[("QB One", "QB")], picks_b=[("RB One", "RB")])
    df = my_roster_lineup_report(ctx)
    assert "QB One" in df["Player"].values
    assert "RB One" not in df["Player"].values  # that's Team B's pick, not mine
    qb_row = df[df["Roster Position"] == "QB"].iloc[0]
    assert qb_row["Proj Pts"] == 300.0


def test_my_roster_bench_report_empty_when_nothing_overflows(tmp_path):
    ctx = _ctx(tmp_path, picks_a=[("QB One", "QB")])
    df = my_roster_bench_report(ctx)
    assert df.empty


def test_league_rosters_report_returns_one_sheet_per_team(tmp_path):
    ctx = _ctx(tmp_path, picks_a=[("QB One", "QB")], picks_b=[("RB One", "RB")])
    sheets = league_rosters_report(ctx)
    assert set(sheets.keys()) == {"Team A", "Team B"}
    team_a_df = sheets["Team A"]
    assert "QB One" in team_a_df["Player"].values
    assert "Total Team Points" in team_a_df["Roster Position"].values


def test_opponent_needs_report_empty_on_my_own_pick(tmp_path):
    ctx = _ctx(tmp_path)  # Team A picks first -- it's my turn right now
    df = opponent_needs_report(ctx)
    assert df.empty
    assert list(df.columns) == ["Team", "Likely needs"]


def test_build_workbook_sheets_flattens_single_and_multi_sheet_reports(tmp_path):
    ctx = _ctx(tmp_path, picks_a=[("QB One", "QB")], picks_b=[("RB One", "RB")])
    sheets = build_workbook_sheets(REPORTS, ctx)
    # Single-DataFrame reports contribute one sheet each; league_rosters
    # contributes one sheet per team (2 here) -- total = (len(REPORTS) - 1) + 2.
    assert len(sheets) == (len(REPORTS) - 1) + len(TEAMS)
    assert "Team A" in sheets
    assert "Team B" in sheets


def test_build_workbook_sheets_names_never_collide_across_reports(tmp_path):
    ctx = _ctx(tmp_path)
    sheets = build_workbook_sheets(REPORTS, ctx)
    assert len(sheets) == len(set(sheets.keys()))
