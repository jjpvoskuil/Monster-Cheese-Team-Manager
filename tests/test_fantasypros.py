import json
import os

import pytest

from src.data_sources.fantasypros import POSITION_SLUGS, load_seed_json, parse_position_rows

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "projections", "raw", "fantasypros_2026_raw.json",
)


def _load_raw():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def test_all_positions_parse_to_exactly_ten_rows():
    """FantasyPros' free tier caps every position at 10 players -- this is
    a known, documented limitation, not a parsing bug. Asserting exactly 10
    (not >=) so a future capture that somehow gets more rows is noticed."""
    data = _load_raw()
    for pos in POSITION_SLUGS:
        df = parse_position_rows(pos, data[pos])
        assert len(df) == 10, f"{pos}: expected exactly 10 rows (free-tier cap), got {len(df)}"


def test_josh_allen_qb_row():
    data = _load_raw()
    df = parse_position_rows("qb", data["qb"])
    row = df[df["name"] == "Josh Allen"].iloc[0]
    assert row["nfl_team"] == "BUF"
    assert row["pass_yards"] == 3817.1
    assert row["pass_td"] == 27.4
    assert row["pass_int"] == 11.2
    assert row["rush_yards"] == 586.0
    assert row["rush_td"] == 11.8
    assert row["fumbles_lost"] == 4.1


def test_gibbs_rb_row():
    data = _load_raw()
    df = parse_position_rows("rb", data["rb"])
    row = df[df["name"] == "Jahmyr Gibbs"].iloc[0]
    assert row["nfl_team"] == "DET"
    assert row["rush_yards"] == 1381.2
    assert row["receptions"] == 71.3
    assert row["rec_yards"] == 580.6


def test_mcbride_te_row():
    data = _load_raw()
    df = parse_position_rows("te", data["te"])
    row = df[df["name"] == "Trey McBride"].iloc[0]
    assert row["nfl_team"] == "ARI"
    assert row["receptions"] == 108.9
    assert row["rec_yards"] == 1050.8


def test_aubrey_k_row():
    data = _load_raw()
    df = parse_position_rows("k", data["k"])
    row = df[df["name"] == "Brandon Aubrey"].iloc[0]
    assert row["nfl_team"] == "DAL"
    assert row["fg_made"] == 35.2
    assert row["xp_made"] == 47.6


def test_dst_unit_conversion_and_name_normalization():
    data = _load_raw()
    df = parse_position_rows("dst", data["dst"])
    row = df[df["name"] == "Houston"].iloc[0]
    assert row["position"] == "DST"
    assert row["nfl_team"] == "Houston"
    # raw: ["Houston Texans", "49.5", "14.4", "11.6", "18.3", "2.8", "1.0", "322.1", "5,053.9", "120.4"]
    assert row["def_sacks"] == 49.5
    assert row["def_int"] == 14.4
    assert row["def_fumble_rec"] == 11.6
    assert row["def_td"] == 2.8
    assert row["def_safeties"] == 1.0
    assert row["points_allowed_per_game"] == pytest.approx(322.1 / 17)
    assert row["yards_allowed_per_game"] == pytest.approx(5053.9 / 17)


def test_load_seed_json_concatenates_all_positions():
    df = load_seed_json(FIXTURE_PATH)
    assert len(df) == 60  # 6 positions x 10 players
    assert set(df["position"].unique()) == {"QB", "RB", "WR", "TE", "K", "DST"}


def test_suffix_name_split_handles_jr_sr_iii():
    """Player-name tokens like 'Sr.' and 'III' must stay attached to the
    name, not be mistaken for the team code -- team code is always the
    final whitespace token."""
    data = _load_raw()
    df = parse_position_rows("te", data["te"])
    row = df[df["nfl_team"] == "ATL"]
    assert not row.empty
    assert row.iloc[0]["name"] == "Kyle Pitts Sr."

    df_wr = parse_position_rows("wr", data["wr"])
    # A.J. Brown NE -- also exercises a period-containing first name.
    row2 = df_wr[df_wr["nfl_team"] == "NE"]
    assert not row2.empty
    assert row2.iloc[0]["name"] == "A.J. Brown"
