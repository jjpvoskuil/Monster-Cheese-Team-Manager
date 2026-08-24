"""
CBS Sports integration — STUBBED, NOT IMPLEMENTED.

Nice-to-have, not the critical path. Two possible uses if this ever gets
built out:

1. Auto-pulling league scoring/roster settings from the CBS rules page
   (currently done manually — see config/league_settings.yaml header for
   how/when it was captured).
2. Live draft pick sync from the CBS draft room, so the Draft Board doesn't
   need manual pick entry.

Both are blocked on the same practical issue: this app needs an
authenticated CBS session to read league-specific pages, and CBS has no
public API for either of these. The manual pick-entry flow in
pages/1_Draft_Board.py is the reliable fallback and is NOT dependent on
this module — draft day works fine without it.

If picked up later: the CBS draft room's actual live-update mechanism is
unverified (the room hasn't been observed live yet — the boilerplate seen
on related CBS pages mentioning Adobe Flash is almost certainly stale
documentation, not a real dependency). Inspect network requests in the
draft room with browser dev tools once the draft opens, before assuming
any particular approach (websocket vs. polling vs. page scrape).
"""

from __future__ import annotations


def fetch_league_settings(league_url: str) -> dict:
    raise NotImplementedError(
        "CBS auto-pull of league settings is not implemented. "
        "Edit config/league_settings.yaml manually — see its header for "
        "how the current values were captured."
    )


def fetch_live_draft_picks(league_url: str):
    raise NotImplementedError(
        "CBS live draft sync is not implemented. Use the manual 'log a "
        "pick' flow in the Draft Board page instead."
    )
