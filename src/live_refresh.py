"""
Lightweight, dependency-free auto-refresh for pages that show live draft
state (data/draft_state.json can change out from under Streamlit at any
moment via an active Claude session's CBS live-sync -- see
src/live_sync.py -- and Streamlit has no built-in way to notice a file
changed on disk; it only reruns a page in response to a browser-side
event: a click, a widget change, a page switch).

Confirmed missing during the 2026-08-29 mock-draft dry run: picks were
landing in data/draft_state.json in real time (verified on disk), but
every live-data page sat stale until the league manager manually left
and returned to the tab -- exactly the passive "watch it happen" workflow
draft day depends on ("I'll be watching the app... to see how it goes").

Rather than pull in the streamlit-autorefresh package (an extra
dependency the league manager would need to `pip install` into their venv
before draft day, with no time to spare), this embeds a small enough
timed reload via a components.v1 iframe. A full browser reload is blunter
than a true partial rerun (any in-progress filter/scroll/grid-selection
state resets), but it's zero-dependency and guaranteed to work, and these
pages are read-mostly during the actual draft -- the one interactive
piece on the Draft Board (clicking a grid row to log a pick manually) is
a fallback path, not the primary one, since the live sync is what's
expected to log picks on draft day.
"""

from __future__ import annotations

import streamlit as st


def inject_autorefresh(interval_seconds: float = 5.0) -> None:
    """Reload the whole page every `interval_seconds` so any page reading
    data/draft_state.json picks up picks logged by an active live-sync
    session without the user clicking anything. Call once per page,
    anywhere in the page body -- placement only affects where the
    zero-height iframe sits in the DOM, not the reload itself."""
    st.components.v1.html(
        f"""
        <script>
            setTimeout(function() {{
                window.parent.location.reload();
            }}, {int(interval_seconds * 1000)});
        </script>
        """,
        height=0,
    )
