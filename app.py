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

Also injects one small piece of global CSS (2026-08-28, punch-list item
#6): st.metric's value text truncates long strings with an ellipsis by
default (its CSS is `overflow:hidden; text-overflow:ellipsis;
white-space:nowrap`), which clips this league's longer team names on the
Draft Board's "On the clock" metric (e.g. "Mississippi Swamp Ass" in a
~300px sidebar). This shrinks stMetricValue's font a bit and lets it
wrap instead of clip. Applies to every st.metric in the app (also used
by pages/0_League_Settings.py for short values like "8/30/26" -- harmless
there, nothing to wrap). See src/ui_text.py's module docstring for the
matching fix on dataframe "Team" columns.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Monster Cheese Team Manager", page_icon="🏈", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stMetricValue"] {
        font-size: 1.35rem;
        white-space: normal;
        overflow: visible;
        text-overflow: unset;
        line-height: 1.25;
        overflow-wrap: break-word;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

pages = [
    st.Page("pages/0_League_Settings.py", title="League Settings", icon="⚙️", default=True),
    st.Page("pages/1_Draft_Board.py", title="Draft Board", icon="🏈"),
    st.Page("pages/2_Projections.py", title="Projections", icon="📊"),
    st.Page("pages/3_Draft_Tendencies.py", title="Draft Tendencies", icon="📈"),
    st.Page("pages/4_My_Roster.py", title="My Roster", icon="📋"),
    st.Page("pages/5_Development.py", title="Development", icon="🛠️"),
    st.Page("pages/6_League_Rosters.py", title="League Rosters", icon="🏆"),
    st.Page("pages/7_Reports.py", title="Reports", icon="📥"),
]

st.navigation(pages).run()
