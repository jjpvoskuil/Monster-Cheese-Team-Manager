"""
CBS Sports integration.

league settings auto-pull — still STUBBED, NOT IMPLEMENTED. Blocked on
CBS having no public API and requiring an authenticated session; edit
config/league_settings.yaml manually instead (see its header for how the
current values were captured).

Live draft pick sync — IMPLEMENTED, but not in this module and not as a
function this app calls. See src/live_sync.py for the full explanation
of why: it can't be a plain function here because reaching CBS requires
an active Claude session driving a real logged-in browser (Claude in
Chrome) -- there's no public API or unauthenticated endpoint to hit with
a normal HTTP client, which is exactly the blocker described above for
league settings too. src/live_sync.py is the merge/parsing half of that
pipeline (pure functions, fully unit-tested, including against real data
captured from a live CBS mock draft on 2026-08-25); the browser-driving
half is a procedure a Claude session runs during the actual draft, not
code that lives in this repo. The manual "log a pick" flow in
pages/1_Draft_Board.py remains the reliable fallback either way.
"""

from __future__ import annotations


def fetch_league_settings(league_url: str) -> dict:
    raise NotImplementedError(
        "CBS auto-pull of league settings is not implemented. "
        "Edit config/league_settings.yaml manually — see its header for "
        "how the current values were captured."
    )
