import os

import pytest

from src.data_sources.weekly_matchup import (
    MatchupPlayer,
    load_raw_file,
    matchup_to_rows,
    parse_scoring_preview,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_RAW_FILE = os.path.join(ROOT, "data", "weekly_matchups", "raw", "2026_week1.txt")

TEAM_ORDER = [
    "Mississippi Swamp Ass", "Aces High", "THE DEMONS", "Pimp Daddy",
    "Legion of Doom", "Mojo", "Salty Dogs", "Monster Cheese", "Buckhorns", "Ball Busters",
]

# A small, hand-built two-slot matchup in the exact shape parse_scoring_preview
# expects, for tests that don't want to depend on the real capture file.
_MINI_TEXT = """
Scoring Preview
WEEK
WEEK 3 (some date range)
GAMES
BALL BUSTERS @ MONSTER CHEESE
OVERALL
Ball Busters
	0-0-0	RECORD	0-0-0
Monster Cheese
1
	EVEN
	2
QUARTERBACKS

Player Away

QB • AAA
AAA vs. BBB | Sun 1:00PM CT
AAA -1, O/U 40

Player Home

QB • CCC
CCC @ DDD | Sun 1:00PM CT
CCC -1, O/U 40
15
	EVEN
	18

EDGE
SLIGHT
MODERATE

SLIGHT
EDGE
MODERATE

RESERVES
Ball Busters
Monster Cheese
PLAYER	NEWS	MATCHUP	PTS

Bench Away
QB • EEE

Some blurb about this player. ... READ MORE

	EEE vs. FFF
Sun 1:00PM CT	3
PLAYER	NEWS	MATCHUP	PTS

Bench Home
RB • GGG

Another blurb.

With a second paragraph. ... READ MORE

	GGG @ HHH
Sun 1:00PM CT	5
"""


def test_parses_real_2026_week1_capture():
    matchup = load_raw_file(REAL_RAW_FILE, year=2026, team_order=TEAM_ORDER)
    assert matchup.year == 2026
    assert matchup.week == 1
    assert matchup.away_team == "Ball Busters"
    assert matchup.home_team == "Monster Cheese"

    starters = [p for p in matchup.players if p.roster_group == "starter"]
    bench = [p for p in matchup.players if p.roster_group == "bench"]
    assert len(starters) == 24  # 12 slots x 2 teams
    assert len(bench) == 21     # 10 Ball Busters + 11 Monster Cheese (real roster sizes)

    hurts = next(p for p in matchup.players if p.player_name == "Jalen Hurts")
    assert hurts.team == "Ball Busters"
    assert hurts.position == "QB"
    assert hurts.nfl_team == "PHI"
    assert hurts.cbs_points == 22.0
    assert hurts.slot == "Quarterbacks"
    assert hurts.slot_index == 1

    perine = next(p for p in matchup.players if p.player_name == "Samaje Perine")
    assert perine.team == "Monster Cheese"
    assert perine.roster_group == "bench"
    assert perine.cbs_points == 4.0


def test_matchup_to_rows_shape_matches_dataclass_fields():
    matchup = load_raw_file(REAL_RAW_FILE, year=2026, team_order=TEAM_ORDER)
    rows = matchup_to_rows(matchup)
    assert len(rows) == len(matchup.players)
    assert rows[0]["away_team"] == "Ball Busters"
    assert rows[0]["home_team"] == "Monster Cheese"
    assert set(rows[0].keys()) == {
        "year", "week", "away_team", "home_team", "team", "roster_group", "slot",
        "slot_index", "order", "player_name", "position", "nfl_team",
        "matchup_desc", "cbs_points",
    }


def test_minimal_synthetic_matchup_parses_correctly():
    matchup = parse_scoring_preview(_MINI_TEXT, year=2026, team_order=TEAM_ORDER)
    assert matchup.week == 3
    assert matchup.away_team == "Ball Busters"
    assert matchup.home_team == "Monster Cheese"

    starters = [p for p in matchup.players if p.roster_group == "starter"]
    assert len(starters) == 2
    away = next(p for p in starters if p.team == "Ball Busters")
    home = next(p for p in starters if p.team == "Monster Cheese")
    assert away.player_name == "Player Away" and away.cbs_points == 15.0
    assert home.player_name == "Player Home" and home.cbs_points == 18.0

    bench = [p for p in matchup.players if p.roster_group == "bench"]
    assert len(bench) == 2
    assert {p.player_name for p in bench} == {"Bench Away", "Bench Home"}
    bench_home = next(p for p in bench if p.player_name == "Bench Home")
    assert bench_home.position == "RB"
    assert bench_home.nfl_team == "GGG"
    assert bench_home.cbs_points == 5.0


def test_unresolved_team_label_falls_back_to_title_case():
    """No team_order given -- away/home labels should still come through,
    just title-cased instead of matched against real league casing (covers
    a team like "THE DEMONS" NOT being force-titlecased when the config
    list IS given, and the graceful fallback when it isn't)."""
    matchup = parse_scoring_preview(_MINI_TEXT, year=2026, team_order=None)
    assert matchup.away_team == "Ball Busters"
    assert matchup.home_team == "Monster Cheese"


def test_missing_week_line_raises():
    text = _MINI_TEXT.replace("WEEK 3 (some date range)", "nothing here")
    with pytest.raises(ValueError, match="WEEK"):
        parse_scoring_preview(text, year=2026, team_order=TEAM_ORDER)


def test_malformed_position_line_raises():
    text = _MINI_TEXT.replace("QB • AAA", "not a position line")
    with pytest.raises(ValueError, match="POS"):
        parse_scoring_preview(text, year=2026, team_order=TEAM_ORDER)
