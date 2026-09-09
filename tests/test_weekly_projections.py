import os

import pytest

from src.data_sources.weekly_projections import (
    build_lookup,
    canonical_team_abbr,
    load_raw_file,
    match_key,
    parse_weekly_capture,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_RAW_FILE = os.path.join(ROOT, "data", "weekly_projections", "raw", "fantasypoints", "2026_week1_all.txt")

_MINI_TEXT = """
# some header comment lines
# ===== BLOCK 1: rank / name / position / nfl_team =====
1
J. Gibbs
RB
DET
2
J. Jaguars
DST
JAX
# ===== BLOCK 2: opp / fpts =====
NO
23.1
KC
6.2
"""


def test_parses_real_capture():
    rows = load_raw_file(REAL_RAW_FILE)
    assert len(rows) == 526
    top = rows[0]
    assert top["rank"] == 1
    assert top["name"] == "J. Gibbs"
    assert top["position"] == "RB"
    assert top["nfl_team"] == "DET"
    assert top["opp"] == "NO"
    assert top["fpts"] == 23.1

    allen = next(r for r in rows if r["name"] == "J. Allen" and r["position"] == "QB")
    assert allen["nfl_team"] == "BUF"
    assert allen["fpts"] > 0


def test_dst_team_abbr_canonicalized():
    rows = load_raw_file(REAL_RAW_FILE)
    jax_dst = next(r for r in rows if r["position"] == "DST" and r["name"] == "J. Jaguars")
    # FantasyPoints prints "JAX" -- canonicalized to CBS's "JAC"
    assert jax_dst["nfl_team"] == "JAC"


def test_minimal_synthetic_capture():
    rows = parse_weekly_capture(_MINI_TEXT)
    assert len(rows) == 2
    assert rows[0] == {
        "rank": 1, "name": "J. Gibbs", "position": "RB", "nfl_team": "DET",
        "opp": "NO", "fpts": 23.1, "match_key": "J|gibbs|DET",
    }
    assert rows[1]["match_key"] == "DST|JAC"


def test_mismatched_block_lengths_raise():
    bad = _MINI_TEXT + "\nextra_line_makes_block2_odd\n"
    with pytest.raises(ValueError):
        parse_weekly_capture(bad)


@pytest.mark.parametrize("raw,canonical", [
    ("BLT", "BAL"), ("JAX", "JAC"), ("ARZ", "ARI"), ("CLV", "CLE"),
    ("HST", "HOU"), ("LA", "LAR"), ("PHI", "PHI"), ("kc", "KC"),
])
def test_canonical_team_abbr(raw, canonical):
    assert canonical_team_abbr(raw) == canonical


def test_match_key_matches_full_name_to_abbreviated_name():
    # CBS gives full names, FantasyPoints abbreviates the first name --
    # both should produce the same key for the same player.
    cbs_key = match_key("Josh Allen", "QB", "BUF")
    fp_key = match_key("J. Allen", "QB", "BUF")
    assert cbs_key == fp_key


def test_match_key_handles_team_abbreviation_mismatch():
    cbs_key = match_key("Derrick Henry", "RB", "BAL")   # CBS-style abbreviation
    fp_key = match_key("D. Henry", "RB", "BLT")          # FantasyPoints-style
    assert cbs_key == fp_key


def test_match_key_is_suffix_insensitive():
    cbs_key = match_key("Chris Godwin", "WR", "TB")          # CBS drops the suffix
    fp_key = match_key("C. Godwin Jr.", "WR", "TB")           # FantasyPoints keeps it
    assert cbs_key == fp_key


def test_match_key_dst_ignores_name_entirely():
    # FantasyPoints' "name" for a DST is a fake initial + partial city
    # ("C. Bears") that has nothing to do with CBS's own DST naming
    # ("Bears") -- only the team should matter.
    assert match_key("C. Bears", "DST", "CHI") == match_key("Bears", "DST", "CHI")


def test_build_lookup_maps_key_to_fpts():
    rows = parse_weekly_capture(_MINI_TEXT)
    lookup = build_lookup(rows)
    assert lookup["J|gibbs|DET"] == 23.1
    assert lookup["DST|JAC"] == 6.2
