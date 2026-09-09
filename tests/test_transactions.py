import os
import tempfile
from datetime import datetime

from src.data_sources.transactions import (
    _classify_action,
    _parse_cost,
    _parse_date,
    _parse_player_and_action,
    discover_raw_files,
    parse_raw_file,
    parse_raw_files,
)


def test_parse_player_and_action_waiver_add():
    out = _parse_player_and_action("Tre Tucker WR • LV  - Added off Waivers")
    assert out["player_name"] == "Tre Tucker"
    assert out["position"] == "WR"
    assert out["nfl_team"] == "LV"
    assert out["action_text"] == "Added off Waivers"


def test_parse_player_and_action_drop():
    out = _parse_player_and_action("Adam Randall RB • BAL  - Dropped")
    assert out["player_name"] == "Adam Randall"
    assert out["position"] == "RB"
    assert out["nfl_team"] == "BAL"
    assert out["action_text"] == "Dropped"


def test_parse_player_and_action_trade():
    out = _parse_player_and_action("Packers DST • GB - Traded from THE DEMONS")
    assert out["player_name"] == "Packers"
    assert out["position"] == "DST"
    assert out["nfl_team"] == "GB"
    assert out["action_text"] == "Traded from THE DEMONS"


def test_parse_player_and_action_blank_nfl_team():
    out = _parse_player_and_action("Some Guy RB •  - Added off Waivers")
    assert out["nfl_team"] is None


def test_classify_action_waiver_add():
    assert _classify_action("Added off Waivers") == ("waiver_add", None)


def test_classify_action_drop():
    assert _classify_action("Dropped") == ("drop", None)


def test_classify_action_trade():
    assert _classify_action("Traded from THE DEMONS") == ("trade_in", "THE DEMONS")


def test_classify_action_unrecognized_falls_back_to_other():
    assert _classify_action("Something CBS has never shown before") == ("other", None)


def test_parse_cost():
    assert _parse_cost("$10.00") == 10.0
    assert _parse_cost("$0.00") == 0.0
    assert _parse_cost("") is None


def test_parse_date():
    d = _parse_date("9/3/26 3:25 AM ET")
    assert d == datetime(2026, 9, 3, 3, 25)


def test_parse_date_unrecognized_returns_none():
    assert _parse_date("not a date") is None


def test_parse_raw_file_real_2026_capture():
    """Regression test against the real capture this feature shipped
    with (data/transactions/raw/2026_raw.txt) -- catches any future
    parser change that would silently misparse real data."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "transactions", "raw", "2026_raw.txt",
    )
    txns = parse_raw_file(path, 2026)
    assert len(txns) == 10
    types = [t.txn_type for t in txns]
    assert types.count("waiver_add") == 7
    assert types.count("drop") == 1
    assert types.count("trade_in") == 2

    monster_cheese = [t for t in txns if t.team == "Monster Cheese"]
    assert len(monster_cheese) == 1
    assert monster_cheese[0].player_name == "Samaje Perine"
    assert monster_cheese[0].position == "RB"
    assert monster_cheese[0].txn_type == "waiver_add"

    trade_rows = [t for t in txns if t.txn_type == "trade_in"]
    by_team = {t.team: t for t in trade_rows}
    assert by_team["Buckhorns"].player_name == "Packers"
    assert by_team["Buckhorns"].from_team == "THE DEMONS"
    assert by_team["THE DEMONS"].player_name == "Fernando Mendoza"
    assert by_team["THE DEMONS"].from_team == "Buckhorns"


def test_parse_raw_file_sorted_chronologically():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "transactions", "raw", "2026_raw.txt",
    )
    txns = parse_raw_files({2026: path})
    dates = list(txns["date"])
    assert dates == sorted(dates)


def test_parse_raw_file_dedups_repeated_lines():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        line = "9/3/26 3:25 AM ET\tAces High\tTre Tucker WR • LV  - Added off Waivers\t1\t$10.00\n"
        f.write(line * 3)
        path = f.name
    try:
        txns = parse_raw_file(path, 2026)
        assert len(txns) == 1
    finally:
        os.unlink(path)


def test_parse_raw_file_malformed_line_raises():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("not enough tabs here\n")
        path = f.name
    try:
        try:
            parse_raw_file(path, 2026)
            assert False, "expected ValueError"
        except ValueError:
            pass
    finally:
        os.unlink(path)


def test_discover_raw_files():
    raw_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "transactions", "raw",
    )
    found = discover_raw_files(raw_dir)
    assert 2026 in found
    assert found[2026].endswith("2026_raw.txt")


def test_discover_raw_files_missing_dir():
    assert discover_raw_files("/no/such/dir") == {}
