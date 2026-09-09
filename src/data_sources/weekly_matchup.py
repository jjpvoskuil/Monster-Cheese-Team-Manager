"""
Parse a raw-captured CBS "Scoring Preview" page (one specific week's
matchup for a fantasy team) into a canonical weekly-matchup table.

Why this exists / design choice (2026-09-09): the league manager asked
for a weekly matchup page whose STARTING LINEUPS AND BENCH -- for both
Monster Cheese and that week's opponent -- come directly from CBS,
rather than being recomputed by this app's own src/roster_needs.py
heuristic. CBS's in-league "Scoring Preview" page
(https://<league>.football.cbssports.com/scoring/preview/<week>/<game>)
already shows exactly that: both teams' real starters (grouped by the
actual slot CBS has them in that week) plus both benches, each row
carrying CBS's own SportsLine-powered point projection for that single
week. See SESSION_NOTES.md's 2026-09-09 entry cross-validating those
per-slot point totals against this app's own tiered scoring formula
(src/scoring.py) applied to CBS's raw per-week stat projections -- close
enough (within ~0.3%) that CBS's own FPTS column here is trusted
directly rather than re-derived from raw stats.

CAPTURE METHOD: no plain-HTTP path -- like cbs.py/fantasypoints.py, this
is a login-gated page (the league manager's own CBS session), captured
via a live Claude session driving a real logged-in browser and saved
with get_page_text(), raw and unmodified apart from stripping to
non-blank lines (this parser does that itself -- see _nonblank_lines).
Saved to data/weekly_matchups/raw/{year}_week{N}.txt. Re-run per week:
each week's matchup is a different CBS URL (different opponent), found
by clicking through "My Team" -> that week's scoring preview, not a
predictable URL pattern -- ask Claude to "capture this week's matchup".

PAGE LAYOUT (see the raw capture file's own header comment for the
exact reasoning): a fixed sequence of STARTER slot sections (heading,
then 1+ "rows" of away-player-block / home-player-block / a 3-number
scoring line / ignorable "edge meter" labels), then one RESERVES
(bench) section holding two "PLAYER NEWS MATCHUP PTS" tables back to
back (away bench, then home bench). This parser drops all blank lines
first and then walks the remaining lines as a small state machine --
far more robust to incidental whitespace/line-count drift between CBS
page renders (or between this file's manual transcription and the live
page) than a multi-line regex would be.

KNOWN LIMITATION: rows under the "FLEX WR/TES" and "FLEX" headings show
position as the generic "WR-TE" (or, for the general FLEX slot, whatever
CBS actually started there) rather than the player's true position --
that's CBS's own display choice for flex-eligible slots, not a parsing
gap. Fine for display (this page just shows CBS's own label); NOT
reliable for joining against a true-position source like FantasyPoints,
so src/data_sources/weekly_projections.py's name-matching deliberately
does not require position to match, only (normalized name, nfl_team).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Fixed vocabulary this parser depends on -- if CBS ever renames a slot
# heading, rows under it will stop being recognized (fails loud via the
# "unrecognized content" ValueError below, not a silent skip).
SLOT_HEADINGS = {
    "QUARTERBACKS", "RUNNING BACKS", "TIGHT ENDS", "FLEX WR/TES",
    "KICKERS", "DEFENSE/STS", "FLEX",
}
_NOISE_LINES = {"EVEN", "EDGE", "SLIGHT", "MODERATE"}
_POS_LINE_RE = re.compile(r"^(?P<pos>[A-Z][A-Z\-]*)\s*•\s*(?P<team>[A-Z]{2,4})$")
_PTS_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_OPP_LINE_RE = re.compile(r"^[A-Za-z.]+ (vs\.|@) [A-Za-z.]+$")
_WEEK_RE = re.compile(r"WEEK\s+(\d+)\s*\(")


@dataclass
class MatchupPlayer:
    team: str          # fantasy team name, e.g. "Monster Cheese"
    roster_group: str  # "starter" or "bench"
    slot: str           # CBS's own slot heading, e.g. "Quarterbacks"; "Bench" for reserves
    slot_index: int     # 1-based row within that slot (2nd QB row, 3rd RB row, ...); 0 for bench
    order: int          # overall display order within (team, roster_group)
    player_name: str
    position: str        # CBS's own position code for this row -- see module
                          # docstring's KNOWN LIMITATION for FLEX rows
    nfl_team: str
    matchup_desc: str    # e.g. "PHI vs. WAS | Sun 3:25PM CT" (starters) or
                          # "PHI vs. WAS" (bench, time is a separate field CBS
                          # renders as its own line -- folded in here as-is)
    cbs_points: float


@dataclass
class WeeklyMatchup:
    year: int
    week: int
    away_team: str
    home_team: str
    players: list[MatchupPlayer] = field(default_factory=list)

    def team_players(self, team: str) -> list[MatchupPlayer]:
        return [p for p in self.players if p.team == team]


def _nonblank_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _resolve_team_label(raw_label: str, team_order: list[str] | None) -> str:
    """CBS's "GAMES" line prints team names in caps ("BALL BUSTERS"). Match
    against the league's real team names (config draft.team_order) to get
    proper casing (e.g. "THE DEMONS" is deliberately all-caps in real
    league data -- title-casing everything would be wrong for that team).
    Falls back to title-case if no config list is given or nothing matches,
    so this module still works from a bare raw-text file with no config."""
    if team_order:
        for name in team_order:
            if name.upper() == raw_label.upper():
                return name
    return raw_label.title()


def parse_scoring_preview(text: str, year: int, team_order: list[str] | None = None) -> WeeklyMatchup:
    lines = _nonblank_lines(text)

    week_match = next((m for m in (_WEEK_RE.search(ln) for ln in lines) if m), None)
    if not week_match:
        raise ValueError("Could not find a 'WEEK N (...)' line in the raw capture")
    week = int(week_match.group(1))

    games_idx = lines.index("GAMES")
    matchup_line = lines[games_idx + 1]
    if "@" not in matchup_line:
        raise ValueError(f"Expected 'AWAY @ HOME' after GAMES, got {matchup_line!r}")
    away_raw, home_raw = [s.strip() for s in matchup_line.split("@", 1)]
    away_team = _resolve_team_label(away_raw, team_order)
    home_team = _resolve_team_label(home_raw, team_order)

    players: list[MatchupPlayer] = []
    away_order = 0
    home_order = 0

    # ---- Starters: walk from the first slot heading up to "RESERVES" ----
    idx = next(i for i, ln in enumerate(lines) if ln in SLOT_HEADINGS)
    current_slot = None
    slot_index = 0
    while lines[idx] != "RESERVES":
        line = lines[idx]
        if line in SLOT_HEADINGS:
            current_slot = line.title().replace("Wr/Tes", "WR/TEs").replace("Sts", "STs")
            slot_index = 0
            idx += 1
            continue

        slot_index += 1

        def _read_player_block(i: int):
            name = lines[i]
            m = _POS_LINE_RE.match(lines[i + 1])
            if not m:
                raise ValueError(f"Expected 'POS • TEAM' at line {i + 1!r}, got {lines[i + 1]!r}")
            # lines[i+2] = game/time, lines[i+3] = spread/O-U (both folded
            # into matchup_desc; kept together since neither is needed
            # separately anywhere downstream).
            matchup_desc = f"{lines[i + 2]} | {lines[i + 3]}" if "|" not in lines[i + 2] else lines[i + 2]
            return name, m.group("pos"), m.group("team"), matchup_desc, i + 4

        away_name, away_pos, away_team_abbr, away_desc, idx = _read_player_block(idx)
        home_name, home_pos, home_team_abbr, home_desc, idx = _read_player_block(idx)

        if not _PTS_RE.match(lines[idx]):
            raise ValueError(f"Expected away points at line {idx!r}, got {lines[idx]!r}")
        away_pts = float(lines[idx]); idx += 1
        if lines[idx] != "EVEN":
            raise ValueError(f"Expected 'EVEN' at line {idx!r}, got {lines[idx]!r}")
        idx += 1
        if not _PTS_RE.match(lines[idx]):
            raise ValueError(f"Expected home points at line {idx!r}, got {lines[idx]!r}")
        home_pts = float(lines[idx]); idx += 1

        away_order += 1
        home_order += 1
        players.append(MatchupPlayer(away_team, "starter", current_slot, slot_index, away_order,
                                      away_name, away_pos, away_team_abbr, away_desc, away_pts))
        players.append(MatchupPlayer(home_team, "starter", current_slot, slot_index, home_order,
                                      home_name, home_pos, home_team_abbr, home_desc, home_pts))

        while idx < len(lines) and lines[idx] in _NOISE_LINES:
            idx += 1

    # ---- Bench: two "PLAYER ... PTS" tables back to back ----
    idx += 1  # past "RESERVES"
    idx += 2  # past the two bare team-name lines (already known from GAMES line)

    def _parse_bench_table(i: int, team: str, start_order: int):
        assert lines[i].startswith("PLAYER") and "PTS" in lines[i]
        i += 1
        order = start_order
        while i < len(lines) and not (lines[i].startswith("PLAYER") and "PTS" in lines[i]) and lines[i] != "More":
            name = lines[i]; i += 1
            m = _POS_LINE_RE.match(lines[i])
            if not m:
                raise ValueError(f"Expected 'POS • TEAM' at line {i!r}, got {lines[i]!r}")
            pos, team_abbr = m.group("pos"), m.group("team")
            i += 1
            while i < len(lines) and not _OPP_LINE_RE.match(lines[i]):
                i += 1
            if i >= len(lines):
                raise ValueError(f"Ran off the end looking for an opponent line for {name!r}")
            opp_line = lines[i]; i += 1
            time_pts_line = lines[i]; i += 1
            if "\t" not in time_pts_line:
                raise ValueError(f"Expected a tab-separated 'TIME\\tPTS' line, got {time_pts_line!r}")
            pts = float(time_pts_line.rsplit("\t", 1)[-1])
            order += 1
            players.append(MatchupPlayer(team, "bench", "Bench", 0, order, name, pos, team_abbr, opp_line, pts))
        return i, order

    idx, away_order = _parse_bench_table(idx, away_team, away_order)
    idx, home_order = _parse_bench_table(idx, home_team, home_order)

    return WeeklyMatchup(year=year, week=week, away_team=away_team, home_team=home_team, players=players)


def load_raw_file(path: str, year: int, team_order: list[str] | None = None) -> WeeklyMatchup:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # Strip this module's own leading "# ..." documentation comment block
    # (everything up to and including the "===== RAW TEXT BELOW ====="
    # marker line) so callers can hand the file straight through without
    # pre-processing -- see data/weekly_matchups/raw/*.txt's header.
    marker = "===== RAW TEXT BELOW ====="
    if marker in text:
        text = text.split(marker, 1)[1]
    return parse_scoring_preview(text, year=year, team_order=team_order)


def matchup_to_rows(matchup: WeeklyMatchup) -> list[dict]:
    """Flatten a WeeklyMatchup to plain dicts, ready for pd.DataFrame() --
    the canonical shape saved to data/weekly_matchups/{year}_week{N}.csv."""
    return [
        {
            "year": matchup.year, "week": matchup.week,
            "away_team": matchup.away_team, "home_team": matchup.home_team,
            "team": p.team, "roster_group": p.roster_group, "slot": p.slot,
            "slot_index": p.slot_index, "order": p.order,
            "player_name": p.player_name, "position": p.position, "nfl_team": p.nfl_team,
            "matchup_desc": p.matchup_desc, "cbs_points": p.cbs_points,
        }
        for p in matchup.players
    ]
