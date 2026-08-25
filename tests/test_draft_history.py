import os
import tempfile

import pandas as pd

from src.data_sources.draft_history import (
    _parse_player_cell,
    discover_raw_files,
    parse_raw_file,
    parse_raw_files,
)


def test_parse_player_cell_basic():
    out = _parse_player_cell("Josh Allen QB • BUF")
    assert out == dict(
        player_name="Josh Allen", positions=["QB"], position="QB",
        nfl_team="BUF", is_auto_pick=False, is_skipped=False,
    )


def test_parse_player_cell_blank_nfl_team():
    out = _parse_player_cell("Ezekiel Elliott RB •")
    assert out["player_name"] == "Ezekiel Elliott"
    assert out["position"] == "RB"
    assert out["nfl_team"] is None


def test_parse_player_cell_auto_pick():
    out = _parse_player_cell("*Austin Hooper TE • ATL")
    assert out["is_auto_pick"] is True
    assert out["player_name"] == "Austin Hooper"
    assert out["position"] == "TE"


def test_parse_player_cell_dual_position_uses_first_as_primary():
    out = _parse_player_cell("Taysom Hill QB,TE • NO")
    assert out["positions"] == ["QB", "TE"]
    assert out["position"] == "QB"


def test_parse_player_cell_dst():
    out = _parse_player_cell("Eagles DST • PHI")
    assert out["player_name"] == "Eagles"
    assert out["position"] == "DST"
    assert out["nfl_team"] == "PHI"


def test_parse_player_cell_skipped_pick():
    out = _parse_player_cell("(Skipped Pick)")
    assert out["is_skipped"] is True
    assert out["player_name"] is None
    assert out["position"] is None


def test_parse_raw_file_computes_overall_pick_from_round_and_teams_per_round():
    raw = (
        "1|1|Team A|Josh Allen QB • BUF\n"
        "1|2|Team B|Derrick Henry RB • BAL\n"
        "2|1|Team B|Joe Mixon RB • HOU\n"
        "2|2|Team A|Lamar Jackson QB • BAL\n"
    )
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "2099_raw.txt")
        with open(path, "w") as f:
            f.write(raw)
        picks = parse_raw_file(path, year=2099)

    assert [p.overall_pick for p in picks] == [1, 2, 3, 4]
    assert picks[2].team == "Team B"  # round 2 pick 1 (snake continuation not assumed here)
    assert picks[0].year == 2099


def test_parse_raw_files_combines_and_sorts_multiple_years():
    with tempfile.TemporaryDirectory() as d:
        p1 = os.path.join(d, "2099_raw.txt")
        p2 = os.path.join(d, "2100_raw.txt")
        with open(p1, "w") as f:
            f.write("1|1|Team A|Josh Allen QB • BUF\n")
        with open(p2, "w") as f:
            f.write("1|1|Team A|Derrick Henry RB • BAL\n")
        df = parse_raw_files({2099: p1, 2100: p2})

    assert list(df["year"]) == [2099, 2100]
    assert isinstance(df, pd.DataFrame)


def test_discover_raw_files_finds_year_named_files_only():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "2022_raw.txt"), "w").close()
        open(os.path.join(d, "2023_raw.txt"), "w").close()
        open(os.path.join(d, "notes.txt"), "w").close()
        found = discover_raw_files(d)

    assert set(found.keys()) == {2022, 2023}


def test_real_2022_2023_2024_2025_raw_files_parse_cleanly():
    """Regression / integration check against the actual captured data:
    every year should have exactly 22 rounds x 10 picks = 220 picks, and
    the two known 2022 skipped picks should be the only rows with no
    position."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raw_dir = os.path.join(root, "data", "draft_history", "raw")
    paths_by_year = discover_raw_files(raw_dir)
    assert set(paths_by_year.keys()) >= {2022, 2023, 2024, 2025}

    df = parse_raw_files(paths_by_year)
    for year in (2022, 2023, 2024, 2025):
        year_df = df[df["year"] == year]
        assert len(year_df) == 220, f"{year}: expected 220 picks, got {len(year_df)}"
        assert year_df["overall_pick"].max() == 220
        assert sorted(year_df["overall_pick"]) == list(range(1, 221))

    no_position = df[df["position"].isna()]
    assert len(no_position) == 2
    assert (no_position["is_skipped"]).all()
