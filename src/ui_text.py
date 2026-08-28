"""
Small formatting/sizing helpers shared across pages/*.py Streamlit UI
code -- kept out of src/draft_state.py etc so the actual draft logic
stays pure and importable without pulling in streamlit.

Punch-list item #6: "On any page that shows the team names, compact the
font so that the whole team name fits without the '...'. If that
doesn't work, abbreviations for the team names is fine as well." This
league's real team names (config/league_settings.yaml -> draft
.team_order) run up to 22 characters ("Mississippi Swamp Ass"), which
Streamlit's default st.dataframe column widths and st.metric font size
both truncate with an ellipsis. Rather than abbreviate (the punch-list
item's own explicit fallback, only "if that doesn't work"), this widens
dataframe "Team" columns to fit the longest configured name exactly, and
app.py injects matching CSS for st.metric ("On the clock") to shrink its
font and allow wrapping instead of clipping -- so no name ever needs
shortening in the first place.
"""

from __future__ import annotations

import streamlit as st


def team_column_width(teams: list[str], per_char: int = 8, pad: int = 24, min_px: int = 90) -> int:
    """Pixel width wide enough to display any name in `teams` in full
    inside a Streamlit dataframe cell, without the grid's default
    ellipsis truncation kicking in. +2 to the longest name accounts for
    a possible "🎯 " prefix marking your own team (see e.g. pages/1_Draft
    _Board.py's sidebar "Next 10 picks" table)."""
    if not teams:
        return min_px
    longest = max(len(t) for t in teams) + 2
    return max(min_px, pad + per_char * longest)


def team_text_column(label: str, teams: list[str]) -> st.column_config.TextColumn:
    """A ready-to-use st.column_config.TextColumn for a "Team" (or
    similarly team-name-holding) dataframe column, pre-sized via
    team_column_width() so it never truncates any of `teams`."""
    return st.column_config.TextColumn(label, width=team_column_width(teams))
