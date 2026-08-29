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

Found live during the 2026-08-29 mock-draft dry run's SECOND pass: a
naive `setTimeout` in the component re-arms on every Streamlit script
run, not just on a real full browser reload. Streamlit's own frontend
does more script reruns per "logical" page view than it looks like from
the outside (widget/state hydration passes, etc.), and each one was
spinning up its own independent 5-second timer stacked on top of
whatever earlier ones hadn't fired yet -- so instead of one reload every
5 seconds, the league manager saw the page reloading (and jumping back to
the top) every 1-2 seconds as the stacked timers fired in an interleaved
cascade. The `window.top.__mcAutorefreshArmed` guard below fixes this: it
marks the OUTER page (shared across every one of this component's iframe
instances on that page load, since they all reach it via `window.top`,
unlike each iframe's own isolated `window`) the first time a timer gets
armed, and every subsequent call -- however many times Streamlit reruns
the script before the next real reload -- just sees the flag set and
does nothing. A genuine full-page reload starts fresh with no flag set,
so exactly one new timer gets armed each real cycle.

Found live during that same pass, once the stacking was fixed: even a
single clean reload every 5 seconds is disruptive on its own, because a
full browser reload always starts a page scrolled to the top -- there's
no way around that after the fact, it's how navigation works. The fix is
to save the scroll position to sessionStorage (survives a reload of the
same tab/origin, unlike a plain JS variable) right before reloading, and
restore it once the fresh page comes back up. Streamlit re-renders the
page progressively rather than all at once, so a restore attempted too
early can land short of the target if the page isn't tall enough yet --
_restoreScroll() below retries for up to ~2 seconds to cover that. Keyed
by pathname so each page (Draft Board, My Roster, ...) remembers its own
scroll position rather than sharing one across all of them.
"""

from __future__ import annotations

import streamlit as st


def inject_autorefresh(interval_seconds: float = 5.0) -> None:
    """Reload the whole page every `interval_seconds` so any page reading
    data/draft_state.json picks up picks logged by an active live-sync
    session without the user clicking anything, restoring scroll position
    across each reload so it doesn't jump to the top. Call once per page,
    anywhere in the page body -- placement only affects where the
    zero-height iframe sits in the DOM, not the reload itself. Safe to
    call on every script rerun -- see the module docstring for why a
    naive version of this without the window.top guards caused a reload
    storm, and then a scroll-to-top jump every cycle once that was fixed."""
    st.components.v1.html(
        f"""
        <script>
            (function() {{
                var key = 'mcAutorefreshScroll:' + window.top.location.pathname;

                if (!window.top.__mcScrollRestored) {{
                    window.top.__mcScrollRestored = true;
                    var saved = window.top.sessionStorage.getItem(key);
                    if (saved !== null) {{
                        var target = parseInt(saved, 10);
                        var attempts = 0;
                        var tryRestore = function() {{
                            window.top.scrollTo(0, target);
                            attempts++;
                            var reachable = window.top.document.documentElement.scrollHeight
                                - window.top.innerHeight >= target - 5;
                            if (!reachable && attempts < 20) {{
                                setTimeout(tryRestore, 100);
                            }}
                        }};
                        tryRestore();
                    }}
                }}

                if (!window.top.__mcAutorefreshArmed) {{
                    window.top.__mcAutorefreshArmed = true;
                    setTimeout(function() {{
                        try {{
                            window.top.sessionStorage.setItem(
                                key, String(window.top.scrollY || 0)
                            );
                        }} catch (e) {{}}
                        window.top.location.reload();
                    }}, {int(interval_seconds * 1000)});
                }}
            }})();
        </script>
        """,
        height=0,
    )
