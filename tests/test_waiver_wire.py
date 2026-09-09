from src.data_sources.waiver_wire import (
    WaiverCandidate,
    candidates_to_rows,
    load_raw_file,
    parse_free_agent_table,
)

# Small, hand-built samples matching the REAL shape confirmed against all
# 6 captured files (data/waiver_wire/raw/*.txt) -- each row-family (offense,
# K, DST) has a different number of stat columns between START and FPTS,
# which is exactly the case this parser is built to not care about.
OFFENSE_SAMPLE = """
Header noise
Header noise 2
ACTION	AVAIL	PLAYER	OPP	OVP	BYE	ROST	START	ATT	COMP	YDS	TD	INT	FPTS


\tW (9/10)\tElic Ayomanor WR • TEN\tNYJ\t17\t9\t6\t1\t0.0\t0.0\t0.0\t0.0\t0.0\t7.51


\tW (9/10)\tTaysom Hill QB,TE • NO\tATL\t5\t11\t20\t2\t0.0\t0.0\t0.0\t0.0\t0.0\t9.30


\tW (9/10)\tTitans DST • TEN \tNYJ\t26\t9\t12\t9\t4.2\t0.8\t0.7\t0.6\t0.2\t8.40
"""

DST_SAMPLE = """
ACTION	AVAIL	PLAYER	OPP	OVP	BYE	ROST	START	SACK	FUM	INT	DWN	TD	STY	AVG	TOTAL	AVG	TOTAL	FPTS


\tW (9/10)\tFalcons DST • ATL \t@PIT\t13\t11\t35\t23\t3.8\t0.6\t0.6\t0.6\t0.1\t0.1\t275.00\t275\t25.80\t25.8\t7.00
"""


def test_parse_offense_rows():
    candidates = parse_free_agent_table(OFFENSE_SAMPLE)
    assert len(candidates) == 3

    wr = candidates[0]
    assert wr == WaiverCandidate(
        name="Elic Ayomanor", position="WR", nfl_team="TEN", opp="NYJ",
        bye_week=9, rost_pct=6.0, fpts=7.51,
    )


def test_parse_dual_eligible_position_normalizes_comma_to_dash():
    # CBS's own dual-eligibility notation ("QB,TE") -> "QB-TE", matching
    # src.lineup_value._is_eligible's split-on-"-" convention so this
    # slots into the same eligibility check the lineup solver uses.
    candidates = parse_free_agent_table(OFFENSE_SAMPLE)
    hill = next(c for c in candidates if c.name == "Taysom Hill")
    assert hill.position == "QB-TE"


def test_parse_dst_row_name_is_mascot_only():
    # A DST's "name" in the PLAYER field is just its city+mascot (CBS's
    # own drafted-DST naming convention) -- confirm the trailing space
    # before "•" (seen in several real captures) doesn't leak into the name.
    candidates = parse_free_agent_table(OFFENSE_SAMPLE)
    titans = next(c for c in candidates if c.position == "DST")
    assert titans.name == "Titans"
    assert titans.nfl_team == "TEN"


def test_parse_dst_table_last_field_is_fpts_regardless_of_stat_count():
    # DST's table has a different (longer) stat-column layout than
    # offense/K -- confirms the "last tab field is always FPTS" parsing
    # holds regardless of how many stat columns come before it.
    candidates = parse_free_agent_table(DST_SAMPLE)
    assert len(candidates) == 1
    assert candidates[0].fpts == 7.00
    assert candidates[0].name == "Falcons"


def test_no_data_rows_raises():
    try:
        parse_free_agent_table("just some header text\nno data here")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_load_raw_file_strips_documentation_header(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text(
        "# some doc header\n# more doc\n# ===== RAW TEXT BELOW =====\n" + OFFENSE_SAMPLE
    )
    candidates = load_raw_file(str(path))
    assert len(candidates) == 3


def test_candidates_to_rows_shape():
    candidates = parse_free_agent_table(OFFENSE_SAMPLE)
    rows = candidates_to_rows(candidates, year=2026, timeframe="week1")
    assert rows[0]["year"] == 2026
    assert rows[0]["timeframe"] == "week1"
    assert set(rows[0].keys()) == {
        "year", "timeframe", "name", "position", "nfl_team", "opp",
        "bye_week", "rost_pct", "fpts",
    }


def test_real_captured_files_all_parse_without_error():
    # Smoke test against the actual 6 raw captures under
    # data/waiver_wire/raw/ -- confirms the parser still handles real CBS
    # output, not just these hand-built samples, and that every row
    # matches (regression guard for the _PLAYER_RE shape).
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raw_dir = os.path.join(root, "data", "waiver_wire", "raw")
    if not os.path.isdir(raw_dir):
        return
    for name in os.listdir(raw_dir):
        if not name.endswith(".txt"):
            continue
        candidates = load_raw_file(os.path.join(raw_dir, name))
        assert len(candidates) > 0, f"{name} produced no candidates"
        for c in candidates:
            assert c.name
            assert c.position
