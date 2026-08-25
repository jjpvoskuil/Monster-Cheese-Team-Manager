import os
import re

import pytest

from src.data_sources.fftoday import POSITION_CONFIG, parse_position_text

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "projections", "raw", "fftoday_2026_raw.txt",
)

_SECTION_RE = re.compile(r"==== (\w+) \(PosID=\d+\) ====")


def _load_sections():
    with open(FIXTURE_PATH) as f:
        text = f.read()
    parts = _SECTION_RE.split(text)
    return {parts[i].lower(): parts[i + 1] for i in range(1, len(parts), 2)}


def test_all_positions_parse_with_expected_depth():
    sections = _load_sections()
    expected_min = {"qb": 40, "rb": 40, "wr": 40, "te": 40, "k": 25, "def": 32}
    for pos, cfg in POSITION_CONFIG.items():
        assert pos in sections, f"missing {pos} section in fixture"
        df = parse_position_text(pos, sections[pos])
        assert len(df) >= expected_min[pos], f"{pos}: only parsed {len(df)} rows"


def test_josh_allen_qb_row():
    sections = _load_sections()
    df = parse_position_text("qb", sections["qb"])
    row = df[df["name"] == "Josh Allen"].iloc[0]
    assert row["position"] == "QB"
    assert row["nfl_team"] == "BUF"
    assert row["pass_yards"] == 3787.0
    assert row["pass_td"] == 26.0
    assert row["rush_yards"] == 567.0
    assert row["games"] == 17


def test_nfl_team_populated_for_all_skill_positions():
    """Regression: the team-code token was parsed for validation but
    previously discarded instead of being stored in the output — every
    skill-position row silently had a blank nfl_team."""
    sections = _load_sections()
    for pos in ("qb", "rb", "wr", "te", "k"):
        df = parse_position_text(pos, sections[pos])
        assert df["nfl_team"].notna().all(), f"{pos}: found rows with missing nfl_team"
        assert (df["nfl_team"] != "").all()


def test_gibbs_rb_row():
    sections = _load_sections()
    df = parse_position_text("rb", sections["rb"])
    row = df[df["name"] == "Jahmyr Gibbs"].iloc[0]
    assert row["rush_yards"] == 1422.0
    assert row["receptions"] == 72.0
    assert row["rec_yards"] == 572.0


def test_dst_unit_conversion_and_name_normalization():
    """FFToday prints season-total points allowed and full 'City Nickname'
    team names -- both need converting to match cbs_2026.csv's convention
    (per-game figures, short city name) so blend_projections() can join
    across sources on name_key."""
    sections = _load_sections()
    df = parse_position_text("def", sections["def"])
    row = df[df["name"] == "Houston"].iloc[0]
    assert row["position"] == "DST"
    assert row["nfl_team"] == "Houston"
    # raw text: "Houston Texans 8 48 10 16 3 325 220.9 107.5 1 1 126.0"
    # pa=325 season total -> 325/17 per game; pa_yd_g + ru_yd_g already per-game
    assert row["points_allowed_per_game"] == pytest.approx(325 / 17)
    assert row["yards_allowed_per_game"] == pytest.approx(220.9 + 107.5)
    assert row["def_sacks"] == 48.0
    assert row["def_fumble_rec"] == 10.0
    assert row["def_int"] == 16.0


def test_unparseable_text_returns_empty_frame():
    df = parse_position_text("qb", "this is not a stats table\njust some words")
    assert df.empty
