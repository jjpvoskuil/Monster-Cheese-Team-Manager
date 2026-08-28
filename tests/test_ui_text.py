from src.ui_text import team_column_width

REAL_TEAMS = [
    "Mississippi Swamp Ass", "Aces High", "THE DEMONS", "Pimp Daddy",
    "Legion of Doom", "Mojo", "Salty Dogs", "Monster Cheese", "Buckhorns",
    "Ball Busters",
]


def test_width_scales_with_the_longest_team_name():
    short = team_column_width(["Aces High", "Mojo"])
    long = team_column_width(REAL_TEAMS)  # includes "Mississippi Swamp Ass" (22 chars)
    assert long > short


def test_width_is_never_below_the_minimum_even_for_short_names():
    assert team_column_width(["A", "B"]) >= 90


def test_width_accounts_for_a_possible_own_team_emoji_prefix():
    # "🎯 " prefix (2 extra display characters) must not make the longest
    # name's text get clipped again -- the padding has to cover it.
    plain = team_column_width(["Mississippi Swamp Ass"])
    with_prefix_budget = team_column_width(["Mississippi Swamp Ass"])
    # Same call either way (the function always budgets +2) -- assert the
    # padding is comfortably more than a naive per-char*len(name) estimate,
    # i.e. there's room left over for the emoji prefix.
    naive = 24 + 8 * len("Mississippi Swamp Ass")
    assert with_prefix_budget > naive
    assert plain == with_prefix_budget


def test_empty_team_list_returns_the_minimum():
    assert team_column_width([]) == 90
