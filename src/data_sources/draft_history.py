"""
Parse completed CBS draft-results pages (actual picks, not just the
pre-draft order handled by draft_order.py) into a canonical per-pick
schema, so historical drafts can be analyzed for positional tendencies
(src/draft_tendencies.py).

Raw input format
-----------------
This module expects a simple pipe-delimited "raw" text file, one line per
pick, in the form:

    <round>|<pick_in_round>|<team name>|<player cell>

This is NOT CBS's own page text — it's a compact intermediate format this
project's workflow produces, because the results page requires a logged
-in session and the on-page text is bulky/inconsistently columned across
seasons (some years show extra Elig/Elapsed Time/Fpts columns, some
don't). The workflow to capture a new year:

  1. Log in to CBS (or use an already-logged-in browser session, e.g.
     Claude in Chrome) and visit the draft-results page for that season.
     Use the "DRAFTS" dropdown to find the right entry — some seasons
     (2022 in this league) have multiple draft entries and only one has
     real pick data; check each candidate for a populated table before
     picking one.
  2. Extract every data row's pick number, team, and player cell (the
     third `<td>` — "<Name> <POS[,POS2]> • <NFLTEAM>") into the
     round|pick|team|player format above, one line per pick, and save it
     to data/draft_history/raw/<year>_raw.txt. (In practice this step
     is done by a small in-page JS snippet + a page-text extraction, to
     work around tooling truncation limits on large single extractions.)
  3. Run scripts/fetch_draft_history.py to parse the raw file(s) into
     the canonical CSV at data/draft_history/draft_history.csv.

Player-cell edge cases observed across 2022-2025 seasons' actual data
(all handled by `_parse_player_cell`):
  - Auto-pick: cell prefixed with "*", e.g. "*Austin Hooper TE • ATL"
    (the "draft robot" filled this pick because the team's clock expired).
  - Free-agent / no NFL team: nothing after the bullet, e.g.
    "Ezekiel Elliott RB •" (trailing bullet, blank team).
  - DST picks: the "player name" is the NFL team's mascot, e.g.
    "Eagles DST • PHI" -- player_name="Eagles", position="DST".
  - Dual-position eligibility: e.g. "Taysom Hill QB,TE • NO" ->
    positions=["QB", "TE"]. DECISION: for positional-tendency counting
    purposes (the whole point of this module), a dual-eligible pick is
    tallied under its FIRST listed position only (`position` field) --
    CBS lists the player's primary/default eligibility first in every
    observed case, and double-counting one pick across two positions
    would inflate per-round position totals. The full list is preserved
    in `positions` for anyone who wants a different tally rule later.
  - Skipped picks (2022 only, 2 occurrences): cell is exactly
    "(Skipped Pick)" -- team's slot passed with no player attached
    (roster was presumably already full, or a league mid-season quirk).
    Represented with player_name=None, position=None, is_skipped=True,
    and EXCLUDED from all positional-tendency counts by default.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import pandas as pd

_KNOWN_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
_POS_ALTERNATION = "|".join(_KNOWN_POSITIONS)
_NAME_POS_RE = re.compile(
    rf"^(?P<name>.+?)\s+(?P<pos>(?:{_POS_ALTERNATION})(?:,(?:{_POS_ALTERNATION}))*)$"
)
_SKIPPED_MARKERS = {"(skipped pick)", "skipped pick"}


@dataclass
class ParsedPick:
    year: int
    round: int
    pick_in_round: int
    overall_pick: int
    team: str
    player_name: str | None
    position: str | None
    positions: list[str] = field(default_factory=list)
    nfl_team: str | None = None
    is_auto_pick: bool = False
    is_skipped: bool = False

    def to_dict(self) -> dict:
        return {
            "year": self.year,
            "round": self.round,
            "pick_in_round": self.pick_in_round,
            "overall_pick": self.overall_pick,
            "team": self.team,
            "player_name": self.player_name,
            "position": self.position,
            "positions": ",".join(self.positions) if self.positions else "",
            "nfl_team": self.nfl_team,
            "is_auto_pick": self.is_auto_pick,
            "is_skipped": self.is_skipped,
        }


def _parse_player_cell(raw: str) -> dict:
    raw = raw.strip()
    if raw.lower() in _SKIPPED_MARKERS:
        return dict(
            player_name=None, positions=[], position=None,
            nfl_team=None, is_auto_pick=False, is_skipped=True,
        )

    is_auto = raw.startswith("*")
    if is_auto:
        raw = raw[1:].strip()

    if "•" in raw:
        left, right = raw.split("•", 1)
    else:
        left, right = raw, ""
    left = left.strip()
    nfl_team = right.strip() or None

    m = _NAME_POS_RE.match(left)
    if m:
        name = m.group("name").strip()
        positions = m.group("pos").split(",")
    else:
        # Unrecognized format (e.g. a position code not in _KNOWN_POSITIONS,
        # or a malformed cell) -- keep the raw name, leave position unknown
        # rather than guessing or raising, so one odd row doesn't kill an
        # entire year's import.
        name = left
        positions = []

    return dict(
        player_name=name or None,
        positions=positions,
        position=positions[0] if positions else None,
        nfl_team=nfl_team,
        is_auto_pick=is_auto,
        is_skipped=False,
    )


def parse_raw_file(path: str, year: int) -> list[ParsedPick]:
    """Parse one data/draft_history/raw/<year>_raw.txt file into a list of
    ParsedPick, one per line. `overall_pick` is derived from the data
    itself (round, pick_in_round, and the max pick_in_round seen per
    round) rather than assumed to be a fixed 10-team league, so this
    keeps working if league size ever changes."""
    with open(path, "r") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]

    raw_rows = []
    for ln in lines:
        parts = ln.split("|", 3)
        if len(parts) != 4:
            raise ValueError(f"{path}: malformed line (expected 4 '|'-separated fields): {ln!r}")
        rnd_s, pick_s, team, player_cell = parts
        raw_rows.append((int(rnd_s), int(pick_s), team.strip(), player_cell))

    teams_per_round = max(p for _, p, _, _ in raw_rows) if raw_rows else 0

    picks = []
    for rnd, pick_in_round, team, player_cell in raw_rows:
        overall = (rnd - 1) * teams_per_round + pick_in_round
        parsed = _parse_player_cell(player_cell)
        picks.append(ParsedPick(
            year=year,
            round=rnd,
            pick_in_round=pick_in_round,
            overall_pick=overall,
            team=team,
            **parsed,
        ))
    return picks


def parse_raw_files(paths_by_year: dict[int, str]) -> pd.DataFrame:
    """Parse multiple years' raw files and return one combined DataFrame,
    sorted by (year, overall_pick)."""
    all_picks: list[ParsedPick] = []
    for year, path in paths_by_year.items():
        all_picks.extend(parse_raw_file(path, year))
    df = pd.DataFrame([p.to_dict() for p in all_picks])
    if df.empty:
        return df
    return df.sort_values(["year", "overall_pick"]).reset_index(drop=True)


def load_draft_history(csv_path: str) -> pd.DataFrame:
    """Load the canonical draft-history CSV written by
    scripts/fetch_draft_history.py."""
    if not os.path.exists(csv_path):
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    # pandas round-trips bool columns fine, but empty positions become NaN
    if "positions" in df.columns:
        df["positions"] = df["positions"].fillna("")
    return df


def discover_raw_files(raw_dir: str) -> dict[int, str]:
    """Find data/draft_history/raw/<year>_raw.txt files and return
    {year: path}, sorted by year. Used by scripts/fetch_draft_history.py
    so adding a new year is just "drop the file in and re-run"."""
    if not os.path.isdir(raw_dir):
        return {}
    found = {}
    for name in sorted(os.listdir(raw_dir)):
        m = re.match(r"^(\d{4})_raw\.txt$", name)
        if m:
            found[int(m.group(1))] = os.path.join(raw_dir, name)
    return found
