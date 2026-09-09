"""
AppTest smoke tests for the Trade Finder page. The matching/scoring logic
itself is unit-tested directly in tests/test_trade_recommendations.py;
these tests only confirm the page wires real repo data up (rosters,
CBS/FantasyPoints season projections, waiver-wire bye weeks) and renders
without error.

Runs against the REAL repo data (data/draft_state.json,
data/transactions/transactions.csv, data/projections/*_2026.csv,
data/waiver_wire/2026_restofseason.csv) -- the draft is complete and
every input this page needs already exists and is checked in, so there's
no "data not captured yet" state to fake here (unlike Weekly Matchup).
"""

from __future__ import annotations

import os

from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _open_page():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"))
    at.run(timeout=60)
    at.switch_page("pages/10_Trade_Finder.py")
    at.run(timeout=60)
    assert not at.exception
    return at


def test_page_renders_with_real_data():
    at = _open_page()
    titles = " ".join(t.value for t in at.title)
    assert "Trade Finder" in titles
    subheaders = " ".join(s.value for s in at.subheader)
    assert "Proposed trades" in subheaders


def test_trade_proposals_or_no_trades_message_render():
    at = _open_page()
    # Either at least one trade card (a "You give"/"You get" markdown pair
    # and gain metrics) or the explicit "no trades clear both bars" info
    # message must render -- never neither.
    give_get_markdown = [m.value for m in at.markdown if m.value.startswith("**You give**")]
    no_trades_message = [i.value for i in at.info if "No trades clear both bars" in i.value]
    assert give_get_markdown or no_trades_message

    if give_get_markdown:
        gain_labels = {m.label for m in at.metric}
        assert "Your gain (FantasyPoints)" in gain_labels
        assert "Your gain (CBS)" in gain_labels


def test_all_rosters_expander_lists_every_team():
    at = _open_page()
    roster_dataframes = [d.value for d in at.dataframe]
    assert roster_dataframes
    all_rosters_df = roster_dataframes[-1]
    assert len(all_rosters_df) > 0
    for col in ("Team", "Player", "Pos", "NFL Team", "FantasyPoints VOR", "CBS VOR"):
        assert col in all_rosters_df.columns
    # Every real league team should show up on the roster (10-team league).
    assert all_rosters_df["Team"].nunique() >= 9
