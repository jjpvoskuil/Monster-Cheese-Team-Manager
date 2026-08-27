"""
Monster Cheese Team Manager — Streamlit multipage entrypoint.

Run with `streamlit run app.py`, same as always. This file itself renders
nothing — it just declares the sidebar navigation (page titles + icons)
via st.navigation() and hands off to whichever page is selected.

Switched from Streamlit's classic pages/-directory auto-discovery to
st.navigation() (2026-08-27) for two cosmetic fixes the league manager
asked for: the old setup had this file's own landing-page content
(league settings summary + draft countdown) living directly in app.py,
which under classic multipage auto-discovery showed up in the sidebar as
the literal filename "app" -- confusing, since it's really a league
-settings page. Classic mode also only picks up a page's sidebar icon
from an emoji embedded in its FILENAME (e.g. "1_🏈_Draft_Board.py"), which
this repo's numbered-but-plain-English filenames (pages/1_Draft_Board.py,
etc.) never used. st.navigation() fixes both in one place: every page
gets an explicit title + icon below, independent of its filename, and
the old landing content moved to pages/0_League_Settings.py with an
actual descriptive title.

The page files themselves (pages/*.py) are unchanged in what they render
-- only st.set_page_config() moved: it can only be called ONCE per app
run, so it lives here now instead of once per page file. Using
st.navigation() in this entrypoint also means Streamlit no longer
auto-discovers pages/ on its own (that auto-discovery is specifically
suppressed whenever the entrypoint calls st.navigation()) -- this list
below is now the single source of truth for what's in the sidebar and in
what order, not the pages/ filenames.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Monster Cheese Team Manager", page_icon="🏈", layout="wide")

pages = [
    st.Page("pages/0_League_Settings.py", title="League Settings", icon="⚙️", default=True),
    st.Page("pages/1_Draft_Board.py", title="Draft Board", icon="🏈"),
    st.Page("pages/2_Projections.py", title="Projections", icon="📊"),
    st.Page("pages/3_Draft_Tendencies.py", title="Draft Tendencies", icon="📈"),
    st.Page("pages/4_My_Roster.py", title="My Roster", icon="📋"),
]

st.navigation(pages).run()
