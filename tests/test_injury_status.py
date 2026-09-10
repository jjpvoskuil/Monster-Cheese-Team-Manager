import pandas as pd

from src.injury_status import build_injury_lookup, capture_summary, injury_badge, load_injury_table

SAMPLE_DF = pd.DataFrame([
    {
        "name": "Sam Darnold", "nfl_team": "SEA", "designation": "Questionable",
        "headline": "Questionable to return", "note": "Darnold (hip) left Wednesday night's contest.",
        "effective_time": "2026-09-10 08:00:00", "source_file": "test.txt",
    },
    {
        "name": "Jeremiyah Love", "nfl_team": "ARI", "designation": "Limited",
        "headline": "Limited at Wednesday's practice", "note": "Love (ankle) was a limited participant.",
        "effective_time": "2026-09-10 07:00:00", "source_file": "test.txt",
    },
    {
        "name": "Dru Phillips", "nfl_team": "NYG", "designation": "Cleared",
        "headline": "Fades injury report", "note": "Phillips (knee) is not listed on Wednesday's injury report.",
        "effective_time": "2026-09-10 09:00:00", "source_file": "test.txt",
    },
])


def test_build_injury_lookup_excludes_cleared_and_notes():
    lookup = build_injury_lookup(SAMPLE_DF)
    assert set(lookup) == {"Sam Darnold", "Jeremiyah Love"}
    assert "Dru Phillips" not in lookup


def test_injury_badge_for_flagged_and_unflagged_players():
    lookup = build_injury_lookup(SAMPLE_DF)
    assert injury_badge("Sam Darnold", lookup) == "❓ Quest."
    assert injury_badge("Jeremiyah Love", lookup) == "⚠️ Limited"
    assert injury_badge("Dru Phillips", lookup) == ""  # cleared -- not flagged
    assert injury_badge("Someone Not In Feed", lookup) == ""


def test_capture_summary_reflects_latest_effective_time():
    df = SAMPLE_DF.copy()
    df["effective_time"] = pd.to_datetime(df["effective_time"])
    summary = capture_summary(df)
    assert summary is not None
    assert "as of" in summary


def test_capture_summary_none_when_empty():
    assert capture_summary(pd.DataFrame(columns=SAMPLE_DF.columns)) is None


def test_load_injury_table_missing_file_returns_empty_frame():
    df = load_injury_table("/tmp/does-not-exist-injury-report.csv")
    assert df.empty
    assert list(df.columns) == [
        "name", "nfl_team", "designation", "headline", "note", "effective_time", "source_file",
    ]


def test_load_injury_table_real_file_if_present():
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "data", "injury_report", "current.csv")
    if not os.path.exists(path):
        return
    df = load_injury_table(path)
    assert not df.empty
    assert df["effective_time"].dtype.kind == "M"  # parsed to datetime
