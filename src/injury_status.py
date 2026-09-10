"""
Shared injury/practice-report status lookup + display, built on
data/injury_report/current.csv (see scripts/fetch_injury_report.py and
src/data_sources/injury_report.py) -- reused by every page that lists
players, per league-manager request (2026-09-10): "we need to make sure
to identify players that are on the injury report or IR. this is
obviously important with starting lineups, waivers, trades and also
during the draft. Beyond an ID....it would be ideal to be able to click
on that icon and get more details about the injury."

ONE lookup, everywhere: rather than each page re-reading the CSV and
re-inventing a badge scheme, pages call `load_injury_table(path)` +
`build_injury_lookup(df)` once each rerun (wrapped in their own
@st.cache_data keyed on the CSV's mtime) and pass the resulting dict to
the two render helpers below.

CACHE-KEY GOTCHA (bit every single page once, 2026-09-10): the mtime
parameter to that per-page cached wrapper function must NOT have a
leading underscore. Streamlit's cache_data silently excludes
underscore-prefixed parameters from the cache key entirely, so a
wrapper like `def _injury_lookup(_mtime: float): ...` only ever runs
ONCE per Streamlit process no matter how many times the mtime argument
actually changes -- the cached (possibly stale, possibly built before
any capture existed) result is returned forever after. This is exactly
why a league-manager report ("Meyers shows on one page but not others,
in the same running app") turned out to be a caching bug, not a data
or name-matching bug: whichever pages a manager had open before a fresh
`data/injury_report/current.csv` was dropped in stayed frozen on their
last cached lookup; a page opened for the first time afterward read the
new file correctly. See pages/1_Draft_Board.py's get_ranked_players()
for the same anti-pattern found earlier against a different cache.

FLAGGED vs. informational: most entries in the underlying feed are
actually good news ("not listed on injury report", "full practice
participant") -- CBS's news ticker mentions a player any time their
practice status is reported, not only when they're hurt. Badging every
one of those "Cleared" mentions would put a badge on nearly every
player in the league and defeat the point (surfacing real lineup risk).
Only designations that represent an actual current concern
(FLAGGED_DESIGNATIONS below) get a badge or show up in the notes
expander; "Cleared"/"Note" entries stay available in the data (a
manager can still see them by reading data/injury_report/current.csv
directly) but don't clutter every page.

Streamlit-dependent by design (like src/ui_text.py) -- this module IS
the shared UI piece, not just the data plumbing underneath it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

FLAGGED_DESIGNATIONS = ("IR", "Out", "Doubtful", "Questionable", "Limited")

# Sort/severity order (most to least concerning) for both badge choice
# ambiguity (a player could theoretically have two flagged rows in a
# multi-file capture, though current.csv already dedupes to one row per
# player) and for ordering the notes expander.
_SEVERITY = {d: i for i, d in enumerate(("IR", "Out", "Doubtful", "Questionable", "Limited"))}

_BADGES = {
    "IR": "🚑 IR", "Out": "❌ Out", "Doubtful": "❓ Doubtful",
    "Questionable": "❓ Quest.", "Limited": "⚠️ Limited",
}
_ICONS = {"IR": "🚑", "Out": "❌", "Doubtful": "❓", "Questionable": "❓", "Limited": "⚠️"}


def load_injury_table(path: str) -> pd.DataFrame:
    """Raw load of data/injury_report/current.csv with `effective_time`
    parsed to a real datetime. Returns an empty (but correctly shaped)
    DataFrame if the file doesn't exist yet -- no capture taken yet is a
    normal state, not an error (mirrors every other data source's
    "nothing captured yet" handling in this app)."""
    columns = ["name", "nfl_team", "designation", "headline", "note", "effective_time", "source_file"]
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame(columns=columns)
    df["effective_time"] = pd.to_datetime(df["effective_time"])
    return df


def build_injury_lookup(df: pd.DataFrame) -> dict[str, dict]:
    """name -> {designation, nfl_team, headline, note, effective_time}
    for FLAGGED rows only (see module docstring) -- exact-name-match
    lookup, same join convention as src/season_scoring's callers use
    against roster player names."""
    flagged = df[df["designation"].isin(FLAGGED_DESIGNATIONS)]
    return {row["name"]: row.to_dict() for _, row in flagged.iterrows()}


def injury_badge(name: str, lookup: dict[str, dict]) -> str:
    """Short badge text for `name`, or "" if not currently flagged --
    build a dataframe column from this via
    `df[name_col].apply(lambda n: injury_badge(n, lookup))`."""
    record = lookup.get(name)
    if not record:
        return ""
    return _BADGES.get(record["designation"], "")


def injury_icon(name: str, lookup: dict[str, dict]) -> str:
    """Just the emoji (no designation text) for `name`, or "" -- for
    space-constrained displays like League Rosters' dense side-by-side
    grid, where the full injury_badge() text badge would overflow an
    already-tight per-team Player column. Pair with a legend/expander so
    the bare emoji still has a plain-text explanation somewhere."""
    record = lookup.get(name)
    if not record:
        return ""
    return _ICONS.get(record["designation"], "")


def capture_summary(df: pd.DataFrame) -> str | None:
    """'as of <latest capture time>' caption text, or None if no data
    captured yet -- surfaces staleness, since unlike season projections
    this is a live ticker that can go stale within hours."""
    if df.empty:
        return None
    latest = df["effective_time"].max()
    return f"Injury/practice-report data as of {latest:%b %d, %Y %-I:%M %p} (re-capture for fresher data)."


def render_injury_notes_expander(
    names: list[str], lookup: dict[str, dict], label: str = "🚑 Injury / practice-report notes",
) -> None:
    """An expander listing CBS's latest practice-report note for every
    flagged player in `names` (most severe first) -- the "get more
    details about the injury" the league manager asked for, alongside
    each page's badge column. Renders nothing at all if no one in
    `names` is currently flagged, rather than an empty expander."""
    flagged = [(n, lookup[n]) for n in names if n in lookup]
    if not flagged:
        return
    flagged.sort(key=lambda item: _SEVERITY.get(item[1]["designation"], 99))
    with st.expander(f"{label} ({len(flagged)})"):
        for name, record in flagged:
            badge = _BADGES.get(record["designation"], record["designation"])
            team = f" • {record['nfl_team']}" if record.get("nfl_team") else ""
            st.caption(f"**{name}**{team} — {badge}: {record['headline']}. {record['note']}")
