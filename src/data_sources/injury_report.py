"""
Injury/practice-report parsing -- league-manager request (2026-09-10):

  "we need to make sure to identify players that are on the injury
  report or IR. this is obviously important with starting lineups,
  waivers, trades and also during the draft. Beyond an ID....it would
  be ideal to be able to click on that icon and get more details about
  the injury."

SOURCE: CBS's "Player News" feed (https://maniacfl.football.cbssports.com
/players, POSITION=ALL, TEAM=ALL PLAYERS) -- a real-time, whole-NFL news
ticker (RotoWire-sourced) covering every team, refreshed every few
minutes. It's the closest thing CBS exposes to a standalone injury
report for fantasy purposes, and it's what feeds the "Player News"
widgets seen elsewhere in the league site. See data/injury_report/raw/
2026_week1_all_pages.txt's header comment for the full capture
procedure and a walkthrough of the entry format this module parses --
2026_week1_page1.txt is an earlier, narrower capture (just the first
of 47 pages) kept for history; a league-manager follow-up (2026-09-10,
"make sure to look for injuries across the entire list of NFL
players", prompted by Jakobi Meyers' Questionable designation not
showing up anywhere -- his news was several pages deep) established
capturing the whole feed at once as the standard going forward.

Most entries are individual defensive players (DB/DL/LB) this league's
DST-only format never rosters -- that's fine and expected. This module
parses every entry it can regardless of position; it's
src/injury_status.py's join against this league's actual rosters
(src.roster_state) that decides which entries matter to any given page.
Junk/irrelevant entries just never match a name and are silently
dropped downstream.

ENTRY FORMAT (per news item, blank lines between sub-parts):
    <Name> <POS> • <TEAM>              (one or more of these header
    ROSTERED BY <TEAM> | FREE AGENT     lines -- header/ownership pairs
    ... (repeated for related links,                for a related player
         e.g. the team DST + team D                 or team DST link,
         entries CBS also shows for a                closest-to-headline
         defensive player's story)                   pair is the real
    <Name> <POS> • <TEAM>                            subject)
    ROSTERED BY <TEAM> | FREE AGENT
    <Team>' <Player Name>: <Headline text>     (or, when no team owns
    BY <SOURCE> | <SOURCE>                      the story, just
                                                 "<Player Name>: <text>")
    <age line -- see below>
    <first body sentence -- the actual status note>

    <second body paragraph of RotoWire color/context -- NOT captured;
     see the raw file's header comment for why>

AGE LINE FORMATS: CBS shows recent entries (roughly the first page or
so of the feed) as a relative age -- "<N> min(s)/hour(s)/hr(s)/day(s)
ago" -- and older entries (once a story rolls off the first page or so)
as an absolute timestamp instead -- "<Month> <D>, <YYYY> <H>:<MM> AM/PM
ET". Both forms are handled here (`AGE_RE`) and by
scripts/fetch_injury_report.py's effective-time calculation (relative
ages are resolved against the raw file's own capture timestamp;
absolute ones are parsed directly and don't need one).

PARSING STRATEGY: anchor on the "BY <SOURCE>" attribution line (always
present, always this exact shape) rather than trying to count fixed
line offsets, since blank-line spacing in a captured page can vary
slightly by source. Walk backward from it (skipping blank lines) to
find the headline line, then the ownership line, then the header line
immediately before that (which is where a reliable team abbreviation
comes from -- RotoWire's headline sometimes uses a shortened first name,
e.g. header "Andru Phillips" vs headline "Dru Phillips", so the header
line is NOT used for the player's name, only for `nfl_team`). Walk
forward from the attribution line (skipping blanks) to find the age
line, then the note line right after it.

DESIGNATION: `classify_designation` is a best-effort keyword read of the
headline + note text, in priority order (IR > Out > Doubtful >
Questionable > Limited > Cleared > Note). It's a quick visual cue, NOT
an authoritative ruling -- the whole point of also keeping `note` is so
a manager can read CBS's own words and judge for themselves, per the
"get more details about the injury" ask above.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ATTRIBUTION_RE = re.compile(r"^BY\s+\S")
OWNERSHIP_RE = re.compile(r"^(ROSTERED BY .+|FREE AGENT)$")
HEADER_RE = re.compile(r"^(?P<name>.+?)\s+(?P<pos>[A-Za-z/]+)\s*•\s*(?P<team>[A-Z]{2,4})\s*$")
HEADLINE_RE = re.compile(r"^(?:[^']+'\s+)?(?P<name>.+?):\s+(?P<headline>.+)$")
AGE_RE = re.compile(
    r"^(\d+\s+(min|mins|hour|hours|hr|hrs|day|days)\s+ago"
    r"|[A-Za-z]+ \d{1,2}, \d{4} \d{1,2}:\d{2} (AM|PM) ET)$"
)

# Checked in order against (headline + " " + note).lower() -- first match wins.
_DESIGNATION_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("IR", ("injured reserve", "reserve/injured", "placed on ir", " to ir")),
    ("Out", ("ruled out", "won't play", "will not play", "downgraded to out", "out for", "is out")),
    ("Doubtful", ("doubtful",)),
    ("Questionable", ("questionable",)),
    ("Limited", ("limited practice", "limited participant", "limited capacity", "limited at", "limited during")),
    (
        "Cleared",
        (
            "not listed on", "no longer on", "not on", "fades injury report", "clears",
            "full participant", "full practice", "full participation", "on pace to play",
            "wasn't listed", "was not listed",
        ),
    ),
]


@dataclass
class InjuryNote:
    name: str
    nfl_team: str | None
    designation: str
    headline: str
    note: str
    age: str


def classify_designation(headline: str, note: str) -> str:
    text = f"{headline} {note}".lower()
    for designation, keywords in _DESIGNATION_RULES:
        if any(kw in text for kw in keywords):
            return designation
    return "Note"


def _prev_nonblank(lines: list[str], i: int) -> int | None:
    i -= 1
    while i >= 0 and not lines[i].strip():
        i -= 1
    return i if i >= 0 else None


def _next_nonblank(lines: list[str], i: int) -> int | None:
    i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return i if i < len(lines) else None


def parse_player_news(text: str) -> list[InjuryNote]:
    """Every parseable entry in a raw CBS Player News capture (see this
    module's docstring for the entry format). Entries this parser can't
    make sense of (unexpected shape near a "BY <SOURCE>" line) are
    silently skipped rather than raising -- this is best-effort news
    parsing, not a strict schema, and one odd entry shouldn't sink the
    whole capture."""
    lines = text.splitlines()
    notes: list[InjuryNote] = []

    for i, line in enumerate(lines):
        if not ATTRIBUTION_RE.match(line.strip()):
            continue

        headline_idx = _prev_nonblank(lines, i)
        if headline_idx is None:
            continue
        headline_match = HEADLINE_RE.match(lines[headline_idx].strip())
        if not headline_match:
            continue

        ownership_idx = _prev_nonblank(lines, headline_idx)
        nfl_team = None
        if ownership_idx is not None and OWNERSHIP_RE.match(lines[ownership_idx].strip()):
            header_idx = _prev_nonblank(lines, ownership_idx)
            if header_idx is not None:
                header_match = HEADER_RE.match(lines[header_idx].strip())
                if header_match:
                    nfl_team = header_match.group("team")

        age_idx = _next_nonblank(lines, i)
        if age_idx is None or not AGE_RE.match(lines[age_idx].strip()):
            continue
        note_idx = _next_nonblank(lines, age_idx)
        if note_idx is None:
            continue

        name = headline_match.group("name").strip()
        headline = headline_match.group("headline").strip()
        note = lines[note_idx].strip()
        notes.append(InjuryNote(
            name=name, nfl_team=nfl_team, designation=classify_designation(headline, note),
            headline=headline, note=note, age=lines[age_idx].strip(),
        ))

    return notes


def notes_to_rows(notes: list[InjuryNote]) -> list[dict]:
    return [
        {
            "name": n.name, "nfl_team": n.nfl_team or "", "designation": n.designation,
            "headline": n.headline, "note": n.note, "age": n.age,
        }
        for n in notes
    ]
