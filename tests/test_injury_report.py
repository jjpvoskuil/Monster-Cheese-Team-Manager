import os

from src.data_sources.injury_report import classify_designation, parse_player_news

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAMPLE = """
Giants DST • NYG
FREE AGENT
Giants D • NYG
FREE AGENT
Andru Phillips DB • NYG
FREE AGENT
Giants' Dru Phillips: Fades injury report
BY ROTOWIRE | ROTOWIRE

11 mins ago
Phillips (knee) is not listed on Wednesday's injury report.

Phillips missed two of the Giants' three preseason games due to a knee injury, but the fact that he was not listed on Wednesday's injury report indicates that he'll play against the Cowboys in Sunday's regular-season opener.

Seahawks TQB • SEA
FREE AGENT
Sam Darnold QB • SEA
ROSTERED BY THE DEMONS
Seahawks' Sam Darnold: Questionable to return
BY ROTOWIRE | ROTOWIRE

15 mins ago
Darnold (hip) left Wednesday night's contest against the Patriots in the first quarter, Curtis Crabtree of Fox 13 Seattle reports.

Darnold suffered a hip injury on the Seahawks' opening possession.

Jeremiyah Love RB • ARI
ROSTERED BY PIMP DADDY
Cardinals' Jeremiyah Love: Limited at Wednesday's practice
BY ROTOWIRE | ROTOWIRE

39 mins ago
Love (ankle) was a limited practice participant Wednesday, Bo Brack of GoPHNX.com reports.

Love's status for Week 1 has been murky since he emerged from the Cardinals' preseason opener with a high-ankle sprain.

Commanders DST • WAS
FREE AGENT
Commanders D • WAS
FREE AGENT
T.J. Maguranyanga DL • WAS
FREE AGENT
T.J. Maguranyanga: Visits Vikings on Monday
BY ROTOWIRE | ROTOWIRE

41 mins ago
Maguranyanga (undisclosed) visited the Vikings on Monday, Aaron Wilson of KPRC 2 Houston reports.

Maguranyanga was recently waived from injured reserve with an injury settlement by the Commanders.
"""


def test_parses_every_entry():
    notes = parse_player_news(SAMPLE)
    assert [n.name for n in notes] == ["Dru Phillips", "Sam Darnold", "Jeremiyah Love", "T.J. Maguranyanga"]


def test_uses_headline_name_not_header_line_name():
    # RotoWire's headline sometimes shortens the header line's name
    # ("Andru Phillips" -> "Dru Phillips") -- the headline's own name is
    # what should be kept, since that's the name tied to the news text.
    notes = parse_player_news(SAMPLE)
    phillips = notes[0]
    assert phillips.name == "Dru Phillips"
    assert phillips.nfl_team == "NYG"


def test_team_prefix_free_headline_still_parses():
    # "T.J. Maguranyanga: Visits Vikings on Monday" has no leading
    # "<Team>' " prefix (the story isn't credited to a team) -- name
    # extraction must not require one.
    notes = parse_player_news(SAMPLE)
    maguranyanga = next(n for n in notes if n.name == "T.J. Maguranyanga")
    assert maguranyanga.nfl_team == "WAS"
    assert maguranyanga.headline == "Visits Vikings on Monday"


def test_designation_classification():
    notes = parse_player_news(SAMPLE)
    by_name = {n.name: n for n in notes}
    assert by_name["Dru Phillips"].designation == "Cleared"
    assert by_name["Sam Darnold"].designation == "Questionable"
    assert by_name["Jeremiyah Love"].designation == "Limited"


def test_classify_designation_priority_order():
    # IR beats every other keyword even if the text also mentions
    # "questionable" elsewhere in the blurb.
    assert classify_designation("Placed on injured reserve", "questionable to return eventually") == "IR"
    assert classify_designation("Ruled out for Sunday", "") == "Out"
    assert classify_designation("Doubtful for Week 1", "") == "Doubtful"
    assert classify_designation("Full practice participant", "") == "Cleared"
    assert classify_designation("Traded to another team", "") == "Note"


def test_note_captures_only_first_body_sentence():
    notes = parse_player_news(SAMPLE)
    darnold = next(n for n in notes if n.name == "Sam Darnold")
    assert darnold.note == "Darnold (hip) left Wednesday night's contest against the Patriots in the first quarter, Curtis Crabtree of Fox 13 Seattle reports."
    assert "suffered a hip injury" not in darnold.note


def test_malformed_entry_is_skipped_not_raised():
    broken = "Just some text\nBY ROTOWIRE | ROTOWIRE\n\n5 mins ago\nSomething happened.\n"
    assert parse_player_news(broken) == []


def test_real_captured_files_all_parse_without_error():
    raw_dir = os.path.join(ROOT, "data", "injury_report", "raw")
    if not os.path.isdir(raw_dir):
        return
    marker = "===== RAW TEXT BELOW =====\n"
    for name in os.listdir(raw_dir):
        if not name.endswith(".txt"):
            continue
        full_text = open(os.path.join(raw_dir, name), encoding="utf-8").read()
        text = full_text.split(marker, 1)[-1]
        notes = parse_player_news(text)
        assert len(notes) > 0, f"{name} produced no notes"
        for n in notes:
            assert n.name
            assert n.designation
            assert n.note
