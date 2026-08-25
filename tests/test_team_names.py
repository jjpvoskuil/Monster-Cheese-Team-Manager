from src.data_sources.team_names import canonical_dst_name


def test_full_name_maps_to_cbs_short_form():
    assert canonical_dst_name("Houston Texans") == "Houston"
    assert canonical_dst_name("Los Angeles Rams") == "L.A. Rams"
    assert canonical_dst_name("Los Angeles Chargers") == "L.A. Chargers"
    assert canonical_dst_name("New York Giants") == "N.Y. Giants"
    assert canonical_dst_name("New York Jets") == "N.Y. Jets"
    assert canonical_dst_name("San Francisco 49ers") == "San Francisco"
    assert canonical_dst_name("Green Bay Packers") == "Green Bay"


def test_already_short_form_passes_through():
    assert canonical_dst_name("Houston") == "Houston"
    assert canonical_dst_name("L.A. Rams") == "L.A. Rams"


def test_all_32_teams_covered():
    from src.data_sources.team_names import _FULL_NAME_TO_CBS
    assert len(_FULL_NAME_TO_CBS) == 32


def test_unknown_name_passes_through_unchanged():
    assert canonical_dst_name("Some Future Team") == "Some Future Team"
