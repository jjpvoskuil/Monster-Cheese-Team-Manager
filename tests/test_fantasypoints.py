import os

import pytest

from src.data_sources.fantasypoints import (
    CAPTURE_FILES,
    load_capture_dir,
    parse_position_csv,
)

CAPTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "projections", "raw", "fantasypoints_capture",
)


def _path(position: str) -> str:
    return os.path.join(CAPTURE_DIR, CAPTURE_FILES[position])


def test_josh_allen_qb_row():
    df = parse_position_csv("QB", _path("QB"))
    row = df[df["name"] == "Josh Allen"].iloc[0]
    assert row["position"] == "QB"
    assert row["nfl_team"] == "BUF"
    assert row["games"] == 15
    assert row["pass_yards"] == 3585.0
    assert row["pass_td"] == 24.6
    assert row["pass_int"] == 11.0
    assert row["rush_yards"] == 523.0
    assert row["rush_td"] == 9.2


def test_gibbs_rb_row():
    df = parse_position_csv("RB", _path("RB"))
    row = df[df["name"] == "Jahmyr Gibbs"].iloc[0]
    assert row["nfl_team"] == "DET"
    assert row["rush_yards"] == 1353.0
    assert row["rush_td"] == 13.5
    assert row["receptions"] == 65.0
    assert row["rec_yards"] == 479.0
    assert row["rec_td"] == 3.2


def test_bowers_te_row():
    df = parse_position_csv("TE", _path("TE"))
    row = df[df["name"] == "Brock Bowers"].iloc[0]
    assert row["nfl_team"] == "LV"
    assert row["receptions"] == 86.0
    assert row["rec_yards"] == 916.0
    assert row["rec_td"] == 6.3


def test_aubrey_k_row():
    df = parse_position_csv("K", _path("K"))
    row = df[df["name"] == "Brandon Aubrey"].iloc[0]
    assert row["nfl_team"] == "DAL"
    assert row["fg_made"] == 31.0
    assert row["xp_made"] == 43.9
    assert row["xp_missed"] == 1.8


def test_dst_name_normalization_and_stats():
    # Regression check for src.data_sources.team_names.canonical_dst_name:
    # this source prints the full "City Nickname" form ("Houston Texans"),
    # same as FantasyPros/FFToday -- must normalize to CBS's short form
    # ("Houston") so blend_projections() joins it with the other sources
    # instead of silently treating it as a second, unrelated "player".
    df = parse_position_csv("DST", _path("DST"))
    assert "Houston Texans" not in df["name"].values
    row = df[df["name"] == "Houston"].iloc[0]
    assert row["position"] == "DST"
    assert row["def_sacks"] == 45.0
    assert row["def_int"] == 14.4
    assert row["def_fumble_rec"] == 8.9
    assert row["def_td"] == 1.9


def test_no_fumbles_lost_or_dst_points_allowed_columns():
    """Documented known gaps (see fantasypoints.py's module docstring):
    this source's export has no fumbles-lost column at all, and DST rows
    have no points/yards-allowed. parse_position_csv() must not invent
    values for either -- they should simply be absent from its output so
    downstream defaulting (manual_import.load_table()) fills 0, not this
    module guessing something the source never actually provided."""
    qb_df = parse_position_csv("QB", _path("QB"))
    assert "fumbles_lost" not in qb_df.columns
    dst_df = parse_position_csv("DST", _path("DST"))
    assert "points_allowed_per_game" not in dst_df.columns
    assert "yards_allowed_per_game" not in dst_df.columns


def test_load_capture_dir_concatenates_all_six_positions():
    df = load_capture_dir(CAPTURE_DIR)
    assert set(df["position"].unique()) == {"QB", "RB", "WR", "TE", "K", "DST"}
    # Matches the real 2026-08-28 capture's row counts exactly (see
    # fantasypoints.py's module docstring) -- a big drop/jump here would
    # mean FantasyPoints changed their export or a future re-capture is
    # importantly different from this one.
    counts = df["position"].value_counts().to_dict()
    assert counts["QB"] == 72
    assert counts["K"] == 32
    assert counts["DST"] == 32


def test_load_capture_dir_raises_clearly_on_an_empty_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_capture_dir(str(tmp_path))
