"""
Sync live picks from the CBS draft room into this app's DraftState, so the
Draft Board reflects real draft-day picks as they happen on CBS — not just
picks logged manually through the app's own "Log a pick" form.

Architecture note (read this before assuming more automation than exists):
this module does NOT reach out to CBS on its own. Nothing in this repo's
deployed Streamlit app can — CBS requires a logged-in session and has no
public API, and the deployed app has no browser of its own. The actual
"reach CBS" step happens in an active Claude session with browser
automation (Claude in Chrome), which extracts the current pick list from
the CBS draft room's results panel into plain data (see
`parse_live_room_dump()` below for the expected shape), and this module
takes it from there: comparing against what DraftState already knows and
appending only genuinely new picks, in order, without disturbing picks
that were logged some other way (e.g. manually, or from an earlier sync
pass).

This is intentionally a MERGE, not a bulk overwrite. DraftState.picks is
an ordered, sequential log (each pick's overall_pick is implicitly
"whatever comes after the last one" — see DraftState.log_pick), so the
merge only ever logs the pick that is exactly `next_overall_pick` next.
If the live source's pick for that slot doesn't match what's already
logged there (shouldn't happen in normal operation, but a stale/corrupt
extraction is exactly the kind of thing this guards against), the merge
stops and reports the mismatch rather than silently overwriting real
draft-day data.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from src.draft_state import DraftState, Pick

_KNOWN_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
_POS_ALTERNATION = "|".join(_KNOWN_POSITIONS)
_NAME_POS_RE = re.compile(
    rf"^(?P<name>.+?)\s+(?P<pos>(?:{_POS_ALTERNATION})(?:,(?:{_POS_ALTERNATION}))*)$"
)


@dataclass
class LivePick:
    """One pick as extracted from the CBS draft room, before it's been
    reconciled against DraftState. `overall_pick` is required -- it's
    the join key the merge uses to figure out what's new."""
    overall_pick: int
    team: str
    player_name: str
    position: str = ""
    nfl_team: str = ""


@dataclass
class SyncResult:
    newly_logged: list[Pick]
    already_known: int
    mismatches: list[str]
    pending_ahead: list[str]

    @property
    def has_mismatch(self) -> bool:
        return bool(self.mismatches)

    def summary(self) -> str:
        parts = [f"{len(self.newly_logged)} new pick(s) logged"]
        if self.already_known:
            parts.append(f"{self.already_known} already known")
        if self.mismatches:
            parts.append(f"{len(self.mismatches)} MISMATCH(ES)")
        if self.pending_ahead:
            parts.append(
                f"{len(self.pending_ahead)} live pick(s) waiting on a gap "
                f"before they can be applied"
            )
        return ", ".join(parts)


def write_sync_status(path: str, draft_state: DraftState, result: SyncResult) -> None:
    """Record that a sync pass just ran, so the Draft Board can show the
    league manager how fresh the live feed is (a live-sync tool that
    silently goes stale mid-draft, with no visible sign of it, is worse
    than no live sync at all -- they'd be making pick decisions off data
    that quietly stopped updating)."""
    payload = {
        "last_sync_at": datetime.now(timezone.utc).isoformat(),
        "last_synced_overall_pick": draft_state.next_overall_pick - 1,
        "newly_logged_this_pass": [p.player_name for p in result.newly_logged],
        "mismatches": result.mismatches,
        "pending_ahead": result.pending_ahead,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def read_sync_status(path: str) -> dict | None:
    """Read back what write_sync_status() wrote, for display in the
    Streamlit app. Returns None if no sync has run yet (not an error --
    a league manager logging picks manually, with no live sync in use at
    all, is the normal case outside of draft day)."""
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None


def parse_player_cell(raw: str) -> tuple[str, str, str]:
    """Parse a "<Name> <POS[,POS2]> • <NFLTEAM>"-style cell (the format
    CBS uses on the HISTORICAL completed-draft results page --
    /draft/results/... -- see src/data_sources/draft_history.py) into
    (player_name, position, nfl_team). NOT the format the live draft
    room uses -- see `parse_live_room_player_cell()` below for that one.
    Kept here for completeness/reuse; minus the auto-pick/skipped-pick
    handling that's specific to the historical-results page."""
    raw = raw.strip().lstrip("*").strip()
    if "•" in raw:
        left, right = raw.split("•", 1)
    else:
        left, right = raw, ""
    left = left.strip()
    nfl_team = right.strip()

    m = _NAME_POS_RE.match(left)
    if m:
        return m.group("name").strip(), m.group("pos").split(",")[0], nfl_team
    return left, "", nfl_team


# ---------------------------------------------------------------------
# LIVE draft room parsing (/draft/live/room2's "Draft Results" panel).
# Confirmed by joining a real CBS mock draft (2026-08-25) and inspecting
# the panel's DOM directly -- this is a DIFFERENT text format than the
# historical completed-draft results page above:
#   historical:  "Josh Allen QB • BUF"
#   live room:   "Allen, Josh (QB BUF)"
# The live room also lists each round's picks in DESCENDING pick order
# (most recent pick first), unlike the historical page's ascending order
# -- parse_live_room_dump() doesn't care either way since it keys off the
# explicit pick number in each row rather than assuming an order.
# ---------------------------------------------------------------------

_LIVE_CELL_RE = re.compile(
    r"^(?P<last>.+?),\s*(?P<first>.+?)\s*\((?P<pos>[A-Z]+(?:,[A-Z]+)*)\s*(?P<team>[A-Z]*)\)$"
)
# Fallback for cells with no "Last, First" comma -- e.g. DST picks, which
# CBS shows as just the team mascot ("Eagles (DST PHI)", unconfirmed
# exact wording but no player has a first/last name to comma-split).
_LIVE_CELL_NO_COMMA_RE = re.compile(
    r"^(?P<name>.+?)\s*\((?P<pos>[A-Z]+(?:,[A-Z]+)*)\s*(?P<team>[A-Z]*)\)$"
)


def parse_live_room_player_cell(raw: str) -> tuple[str, str, str]:
    """Parse a live-draft-room player cell -- "Last, First (POS TEAM)",
    e.g. "Nacua, Puka (WR LAR)" or "Walker III, Kenneth (RB KC)" -- into
    (player_name, position, nfl_team) with player_name normalized to
    "First Last" to match this app's projection data (which uses that
    order everywhere else, e.g. src/data_sources/draft_history.py).
    Dual-position eligibility (if CBS ever shows it here the way it does
    on the historical page, e.g. "(QB,TE NO)") keeps only the first
    -listed position, same rule as draft_history.py, for the same reason
    (avoid double-counting one pick across two positions).

    Confirmed against real data (2026-08-25 mock draft): a pick made by
    a team's autopilot (either an explicitly-enabled autopilot, or an
    empty slot CBS fills itself, shown as team "Auto-Pilot Team N") is
    prefixed with "*", same convention as the historical results page --
    e.g. "*Henry, Derrick (RB BAL)". Stripped before parsing; not
    otherwise tracked, since DraftState.Pick has no such field either."""
    raw = raw.strip().lstrip("*").strip()
    m = _LIVE_CELL_RE.match(raw)
    if m:
        name = f"{m.group('first').strip()} {m.group('last').strip()}"
        position = m.group("pos").split(",")[0]
        return name, position, m.group("team")

    m = _LIVE_CELL_NO_COMMA_RE.match(raw)
    if m:
        position = m.group("pos").split(",")[0]
        return m.group("name").strip(), position, m.group("team")

    # Totally unrecognized shape -- don't crash a live sync over one odd
    # cell, just surface it with no parsed position/team so the caller
    # can decide (e.g. skip it and retry on the next poll).
    return raw, "", ""


def parse_live_room_dump(text: str) -> list[LivePick]:
    """Parse the pipe-delimited "round|pick|team|player_cell" dump
    produced by the live-room extraction snippet (see this module's
    docstring / SESSION_NOTES.md for the exact JS -- it walks
    #DraftRoom.views.results's table after switching the results view to
    "All Results" so every pick made so far is present, not just the
    latest round) into a list of LivePick.

    IMPORTANT, confirmed against real data (2026-08-25 mock draft): the
    live room's "Pick" column is already the OVERALL pick number (it
    keeps counting up across round boundaries -- round 2's picks read
    11, 12, 13...), UNLIKE the historical completed-draft results page
    (src/data_sources/draft_history.py), whose "Pick" column resets to 1
    at the start of every round and has to be combined with the round
    number to get an overall pick. Do NOT apply that same (round-1)*
    teams_per_round+pick arithmetic here -- an earlier version of this
    function did exactly that and silently produced wrong overall_pick
    numbers for every round after the first, which made sync_new_picks
    treat every round-2-onward pick as "not next yet" and stall. The
    `round` field is parsed but only used to double-check ordering, not
    to compute anything.
    """
    picks = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        rnd_s, pick_s, team, player_cell = parts
        try:
            int(rnd_s)
            overall = int(pick_s)
        except ValueError:
            continue
        name, position, nfl_team = parse_live_room_player_cell(player_cell)
        picks.append(LivePick(
            overall_pick=overall, team=team.strip(),
            player_name=name, position=position, nfl_team=nfl_team,
        ))
    return picks


def sync_new_picks(draft_state: DraftState, live_picks: list[LivePick]) -> SyncResult:
    """Reconcile freshly-extracted live picks into draft_state, logging
    only picks that extend the log by exactly one at a time (overall_pick
    == draft_state.next_overall_pick). Returns a SyncResult describing
    what happened so the caller (a Streamlit page, or a live-watch loop)
    can report it without guessing.
    """
    by_pick = {p.overall_pick: p for p in live_picks}
    newly_logged: list[Pick] = []
    mismatches: list[str] = []
    already_known = 0

    while not draft_state.is_draft_complete:
        expected = draft_state.next_overall_pick
        live = by_pick.get(expected)
        if live is None:
            break  # nothing new to apply yet -- wait for the next poll
        logged = draft_state.log_pick(
            team=live.team,
            player_name=live.player_name,
            position=live.position,
            nfl_team=live.nfl_team,
        )
        newly_logged.append(logged)

    # Anything already in draft_state.picks that also appears in
    # live_picks at the same slot is "already known" (a normal steady
    # -state poll after the first one). Anything in live_picks at a slot
    # that's already logged but with DIFFERENT data is a real mismatch
    # worth surfacing -- e.g. the extraction glitched, or two picks got
    # out of order.
    for pick in draft_state.picks:
        live = by_pick.get(pick.overall_pick)
        if live is None:
            continue
        if pick in newly_logged:
            continue
        already_known += 1
        if live.team != pick.team or live.player_name != pick.player_name:
            mismatches.append(
                f"pick #{pick.overall_pick}: app has {pick.team!r}/{pick.player_name!r}, "
                f"live source has {live.team!r}/{live.player_name!r}"
            )

    pending_ahead = [
        f"#{p.overall_pick} {p.team}: {p.player_name}"
        for p in live_picks
        if p.overall_pick > draft_state.next_overall_pick
    ]

    return SyncResult(
        newly_logged=newly_logged,
        already_known=already_known,
        mismatches=mismatches,
        pending_ahead=pending_ahead,
    )
